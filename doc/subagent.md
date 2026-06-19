# Subagent Design

## Scope

Subagents are child conversations launched by a parent agent.

The parent agent asks for subagents through `tool_subagent`. That request is stored as a parent event first. A later backend task initializes child conversations in one transaction, then the parent waits while children run as normal task-driven conversations. When the last child reaches terminal state, the backend wakes the parent so it can continue with one combined subagent result.

This document covers:

- parent and child conversation state
- subagent launch and execution workflow
- parent continuation after child results
- failure behavior
- database state changes
- backend update notifications
- frontend state routing and `MessageSubagent`

General orchestration concepts are in `doc/orchesatrator.md`. Scheduler and lease rules are in `doc/conversation-iter-task.md`.

## Core Concepts

The source of truth is still the database.

- A parent conversation is a normal conversation with `parentId = null`.
- A subagent conversation is a normal conversation with `parentId = parentConversationId`.
- Parent-to-child ordering is stored in `parent.metadata.childConversationIdList`.
- Child events are stored in the child conversation event list.
- Parent events store the subagent launch request, launch result, and final child result summary.
- Frontend state is keyed by conversation ID for both parent and child conversations.

The parent worker must not run child agents inside its own lease. Subagent execution is separate scheduled conversation work.

## Conversation Relationship

`conversation.parentId` defines the durable parent-child relationship.

Root conversations:

- have `parentId = null`
- have a valid `rankGlobal`
- can be reordered in the root conversation list

Subagent conversations:

- have `parentId = parentConversationId`
- have `rankGlobal = ""`
- are ordered by the parent metadata list and child metadata index
- cannot be dragged into the root conversation order
- cannot be renamed, reordered, moved to trashbin, or deleted directly
- are deleted or moved to trashbin with the parent

Parent delete and trashbin actions apply to the whole descendant tree. The backend should run the action in one transaction. If any descendant cannot be updated or deleted, the whole action fails and rolls back.

Parent metadata should contain:

```json
{
  "childConversationIdList": ["123", "124"],
  "subAgentRunById": {
    "run-id": {
      "statusText": "running",
      "childConversationIdList": ["123", "124"],
      "startEventId": "120",
      "resultEventId": "",
      "createdAt": "2026-06-19T08:00:00Z"
    }
  }
}
```

The durable run state should live in dedicated tables. Parent metadata is useful as a read cache and for UI discovery, but it should not be the only state used to coordinate parallel child completion.

Recommended tables:

```text
subagent_run
  runId text primary key
  parentConversationId bigint not null
  requestEventId bigint not null
  startEventId bigint
  resultEventId bigint
  statusText text not null
  childCount integer not null
  childTerminalCount integer not null default 0
  childSuccessCount integer not null default 0
  childFailureCount integer not null default 0
  createAt timestamptz default now()
  updateAt timestamptz default now()

subagent_run_child
  runId text not null
  childConversationId bigint not null
  parentConversationId bigint not null
  childIndex integer not null
  nameText text not null
  statusText text not null
  turnCount integer not null default 0
  latestToolCallJson jsonb
  returnJson jsonb
  failureText text
  createAt timestamptz default now()
  updateAt timestamptz default now()
  primary key (runId, childConversationId)
```

`subagent_run_child` is the place where each child writes its terminal status. The child finish transaction locks and updates its own child row, then locks the run row and checks whether it is the last terminal child.

Child metadata should contain:

```json
{
  "templateKey": "subagent-basic",
  "templateName": "Subagent Basic",
  "statusText": "active",
  "isUserTurn": false,
  "subAgentRunId": "run-id",
  "subAgentName": "math helper",
  "subAgentIndex": 0,
  "subAgentMaxTurns": 6,
  "subAgentInitialPrompt": "Calculate 12 * 7 and return it.",
  "subAgentParentToolCallEventId": "119"
}
```

## Events

The parent conversation uses these events:

- `agentMessage / toolCall`: the parent agent requested `tool_subagent`.
- `orchestratorMessage / subAgentStart`: child conversations were created and scheduled.
- `orchestratorMessage / subAgentResult`: all child conversations reached terminal state.
- `EndAbnormal / BackendException`: parent orchestration failed.

Each child conversation uses normal agent and orchestrator events:

- `orchestratorMessage / textSimple`: child startup prompt.
- `agentMessage / toolCall`: child requested a tool.
- `orchestratorMessage / toolResult`: child tool result.
- `orchestratorMessage / subAgentReturn`: child returned to parent.
- `EndAbnormal / BackendException`: child failed abnormally.

The parent `agentMessage / toolCall` event stores the launch request. The tool call JSON should include a generated `subAgentRunId` before it is committed:

```json
{
  "tool_name": "tool_subagent",
  "args": {
    "subAgentRunId": "run-id",
    "maxTurns": 6,
    "subagents": [
      {
        "name": "math helper",
        "initialPrompt": "Calculate 12 * 7 and return it."
      }
    ]
  }
}
```

The parent `subAgentStart` event is the backend response to that request. It should contain enough data for the UI to render immediately:

```json
{
  "metadata": {
    "schemaVersion": 1,
    "kind": "subAgentStart",
    "subAgentRunId": "run-id"
  },
  "data": [
    {
      "type": "json",
      "data": {
        "statusText": "running",
        "parentConversationId": "100",
        "childConversationIdList": ["123", "124"],
        "subagents": [
          {
            "conversationId": "123",
            "name": "math helper",
            "index": 0,
            "statusText": "running",
            "turnCount": 0,
            "latestToolCall": null
          }
        ]
      }
    }
  ]
}
```

The parent `subAgentResult` event should have the same `subAgentRunId` and one result item per child.

## State Codes

Subagent orchestration uses the existing task-driven columns.

Recommended semantic states:

| Code | Name | Meaning |
| --- | --- | --- |
| `-400` | `TEMPLATE_START_READY` | A template-start iteration should run. Child startup uses this. |
| `-300` | `SUBAGENT_LAUNCH_READY` | Parent has a `tool_subagent` request event and child conversations should be initialized. |
| `-200` | `TOOL_RESULT_READY` | Parent has a tool or subagent result event and should continue the agent loop. |
| `-100` | `USER_MESSAGE_READY` | User message is committed and the agent should run. |
| `100` | `WAIT_USER` | Conversation waits for user input. |
| `200` | `COMPLETED` | Conversation ended normally. |
| `300` | `ARCHIVED` | Conversation is archived. |
| `400` | `WAIT_SUBAGENT` | Parent is waiting for child conversations. No immediate parent iteration is needed. |
| `1000` | `FAILED` | Conversation ended abnormally. |

Negative states mean scheduler-visible work. Positive states mean no immediate scheduler work.

`SUBAGENT_LAUNCH_READY` is only for the backend task that initializes children. A parent waiting for children should use `WAIT_SUBAGENT`, because no parent worker should be assigned while children are still running.

`TEMPLATE_START_READY` is needed for clean task-driven child startup. If the code avoids a new state, it must still store an explicit next iteration type in metadata. The worker should not infer child startup from a missing user event.

## Parent Launch Workflow

The parent starts in normal task-driven user-message iteration.

Initial parent state:

```text
stateCode = USER_MESSAGE_READY
execStatusCode = RUNNING
leaseId = parent worker lease
metadata.isUserTurn = false
```

The parent worker runs the parent orchestrator. If the parent agent calls `tool_subagent`, this worker commits only the request event and moves the parent into a launch-ready state.

The parent request commit should happen in one transaction:

1. Verify the parent lease and version.
2. Create `subAgentRunId`.
3. Append `agentMessage / toolCall` for `tool_subagent`.
4. Insert `subagent_run` with `statusText = launchReady`.
5. Set the parent to launch-ready:

```text
parent.stateCode = SUBAGENT_LAUNCH_READY
parent.execStatusCode = PENDING
parent.leaseId = null
parent.leaseWorkerId = null
parent.leaseExpireAt = null
parent.version += 1
parent.metadata.isUserTurn = false
```

The transaction notifies `conversation_task_ready`. It also triggers `conversation_update` for the parent.

## Child Initialization Workflow

A scheduler leases the parent again because `SUBAGENT_LAUNCH_READY < 0`.

This worker does not call the model. It reads the latest pending `agentMessage / toolCall` for `tool_subagent`, validates the run row, and initializes child conversations.

The child initialization commit should happen in one transaction:

1. Verify the parent lease and version.
2. Lock `subagent_run`.
3. Create each child conversation with `parentId = parentConversationId`.
4. Insert one `subagent_run_child` row for each child.
5. Append child IDs to `parent.metadata.childConversationIdList`.
6. Update `parent.metadata.subAgentRunById[subAgentRunId]`.
7. Append `orchestratorMessage / subAgentStart`.
8. Update `subagent_run.startEventId`.
9. Set parent to waiting:

```text
parent.stateCode = WAIT_SUBAGENT
parent.execStatusCode = IDLE
parent.leaseId = null
parent.leaseWorkerId = null
parent.leaseExpireAt = null
parent.version += 1
parent.metadata.isUserTurn = false
```

Each child is created as scheduled work:

```text
child.parentId = parentConversationId
child.rankGlobal = ""
child.stateCode = TEMPLATE_START_READY
child.execStatusCode = PENDING
child.leaseId = null
child.version = 0
child.metadata.statusText = active
child.metadata.isUserTurn = false
```

The transaction notifies `conversation_task_ready` so child workers can start. It also triggers `conversation_update` for the parent and each child.

## Child Execution Workflow

Each child conversation is leased by a worker like any other task.

When the worker sees:

```text
templateKey = subagent-basic
stateCode = TEMPLATE_START_READY
```

it runs:

```text
run_orchestrator({
  iterType: "templateStart",
  templateKey: "subagent-basic",
  conversationId,
  initialPrompt: metadata.subAgentInitialPrompt,
  maxTurns: metadata.subAgentMaxTurns
})
```

The child worker should commit progress events while it still owns the lease. This lets the frontend show the latest child status.

Progress commit rules:

- verify `leaseId`, `leaseWorkerId`, and current version
- append generated child events
- increment child `version`
- keep `stateCode = TEMPLATE_START_READY`
- keep `execStatusCode = RUNNING`
- keep the same lease
- notify through normal database triggers

When the child yields `orchestratorMessage / subAgentReturn`, the final child commit sets:

```text
child.stateCode = COMPLETED
child.execStatusCode = IDLE
child.leaseId = null
child.leaseWorkerId = null
child.leaseExpireAt = null
child.version += 1
child.metadata.statusText = completed
child.metadata.isUserTurn = false
child.metadata.endStatusText = completed
child.metadata.subAgentResult = {
  "statusText": "completed",
  "isReturned": true,
  "returnValue": {},
  "failureReason": "",
  "turnCount": 4,
  "latestToolCall": {
    "toolName": "tool_calculator",
    "args": {}
  }
}
```

If the child reaches its turn limit without `tool_return_to_parent`, it still commits `orchestratorMessage / subAgentReturn`, but the result is failed:

```text
child.stateCode = FAILED
child.execStatusCode = IDLE
child.metadata.statusText = failed
child.metadata.endStatusText = abnormal
child.metadata.subAgentResult.isReturned = false
```

If the worker crashes or the lease expires, scheduler failure handling marks the child `FAILED` and appends `EndAbnormal / BackendException`.

## Parent Resume Workflow

Child completion should check whether all siblings in the same `subAgentRunId` are terminal.

Terminal child states:

- `COMPLETED`
- `FAILED`
- `ARCHIVED`

If at least one child is still running, only normal update notifications are sent.

Each terminal child commit should:

1. Commit the child terminal event and child terminal conversation state.
2. Lock its `subagent_run_child` row.
3. Set child row `statusText`, `turnCount`, `latestToolCallJson`, `returnJson`, and `failureText`.
4. Lock the `subagent_run` row.
5. Recompute terminal, success, and failure counts from child rows.
6. If not all children are terminal, update the run counts and stop.
7. If all children are terminal, wake the parent.

When all children are terminal, the child finish transaction also writes the parent result:

1. Lock the parent conversation.
2. Read child conversations for the run.
3. Build result data in child index order.
4. Append `orchestratorMessage / subAgentResult` to the parent.
5. Update `parent.metadata.subAgentRunById[subAgentRunId]`.
6. Update `subagent_run.resultEventId` and `statusText`.
7. Set parent continuation state:

```text
parent.stateCode = TOOL_RESULT_READY
parent.execStatusCode = PENDING
parent.leaseId = null
parent.leaseWorkerId = null
parent.leaseExpireAt = null
parent.version += 1
parent.metadata.isUserTurn = false
```

The transaction notifies `conversation_task_ready`.

The next parent worker lease runs the parent orchestrator in continuation mode. The parent agent sees `orchestratorMessage / subAgentResult` as the tool result for `tool_subagent`.

If the parent agent then answers naturally:

```text
parent.stateCode = WAIT_USER
parent.execStatusCode = IDLE
parent.metadata.isUserTurn = true
```

If the parent agent calls another tool, the next state depends on that tool. Another `tool_subagent` call creates a new `subAgentRunId`.

## Failure Behavior

Subagent failure does not automatically fail the parent.

If one child fails:

- the child becomes `FAILED`
- the parent result event includes that child with `statusText = failed`
- the parent result status is `partialFailed`
- the parent resumes after all children are terminal

If all children fail:

- every child result is included
- the parent result status is `failed`
- the parent still resumes so the parent agent can explain or recover

If the parent request commit fails:

- parent retry behavior follows normal worker retry rules
- no run row should remain unless the request event is committed

If child initialization fails before child conversations are committed:

- no child conversations should remain
- the run stays tied to the parent request event
- parent retry behavior follows normal worker retry rules

If child initialization succeeds but parent resume later fails:

- child conversations and run rows stay durable
- parent retry behavior follows normal worker retry rules
- repeated parent resume must not append duplicate `subAgentResult` for the same `subAgentRunId`

If backend restarts while children are running:

- worker rows are recovered through normal scheduler startup rules
- child conversations continue or fail by lease rules
- the parent remains in `WAIT_SUBAGENT` until child terminal state creates `TOOL_RESULT_READY`

## Backend Notifications

Database triggers send `conversation_update` after conversation or event changes.

For child changes, the trigger should notify both:

- the child conversation ID
- the parent conversation ID

This lets the selected parent conversation refresh when a visible child changes.

PostgreSQL notify and WebSocket are refresh hints only. The frontend must refresh from APIs:

- parent conversation row
- parent event list
- child conversation rows for visible subagent runs
- child event lists when child summaries need latest tool call or turn count

The backend should also notify `conversation_task_ready` when:

- child conversations are created with `TEMPLATE_START_READY`
- all children terminal and parent is set to `TOOL_RESULT_READY`
- retry wait becomes ready through scheduler polling

## Frontend Store Design

MobX state should keep parent and child data independently by conversation ID.

Recommended store shape:

```ts
conversationById: Record<string, ConversationItem>
eventListByConversationId: Record<string, EventItem[]>
childConversationIdListByParentId: Record<string, string[]>
subAgentRunViewByEventId: Record<string, SubAgentRunView>
```

The store should support lazy child loading:

- root conversation list loads `parentId = null`
- expanding a parent in the resource tree loads `/api/conversation/list` with `parentId = parentConversationId`
- rendering `MessageSubagent` loads child conversations referenced by the `subAgentStart` event
- child event lists load only when needed for visible status details

Socket routing:

1. Receive `conversationUpdate`.
2. Refresh root list if the changed ID is root or unknown.
3. If the selected conversation matches the changed ID, refresh its events.
4. If the selected conversation has visible subagent runs, refresh the child rows for those runs.
5. If a changed child belongs to the selected parent, refresh the selected parent and the child row.
6. If any visible child is running, keep quiet polling active.

The frontend should not trust socket data as final state.

## Resource Tree

The resource tree should show child conversations below the parent.

Parent item behavior:

- leaf when no child conversations are known
- branch when `childConversationIdList` has items or children were loaded
- click selects the parent conversation
- toggle expands or collapses children

Child item behavior:

- click selects the child conversation
- no root reorder drag
- no `rankGlobal`
- display status beside title when running or failed

Reorder behavior:

- only root conversations can move inside the root conversation branch
- a root conversation cannot be dropped into a parent as child
- a child conversation cannot be dropped into root order
- backend reorder should reject any conversation with `parentId` set

## `MessageSubagent`

`MessageSubagent.tsx` should render `orchestratorMessage / subAgentStart` and update as child conversations change.

It should be used by `Message.tsx` when:

```text
typeText = orchestratorMessage
subtypeText = subAgentStart
```

The card should show:

- run status
- total child count
- completed child count
- failed child count
- one row per child
- child name
- child status
- turn count
- latest child tool call
- loading state when child data is not fetched yet

Running children should show `SpinningCircle`, the same visual pattern used by `MessagePending`.

The card should derive status from durable child conversations, not only from the start event.

Useful derived fields:

```ts
type MessageSubagentChildView = {
  conversationId: string
  name: string
  index: number
  statusText: string
  isRunning: boolean
  turnCount: number
  latestToolCallText: string
  failureReason: string
}
```

Status derivation:

- `isRunning = true` when child `stateCode < 0` or `execStatusCode` is `PENDING`, `RUNNING`, or `RETRY_WAIT`
- `turnCount` comes from `metadata.subAgentResult.turnCount` when terminal, otherwise from child event count or agent tool-call count
- latest tool call comes from the latest child `agentMessage / toolCall`
- failure reason comes from `metadata.subAgentResult.failureReason`, `metadata.endReasonText`, or latest `EndAbnormal / BackendException`

The message card should not block rendering while child data loads. It can show the start-event summary first, then replace rows as child conversation rows and child events are fetched.

## Agent Point Of View

The parent agent sees `tool_subagent` as a normal tool.

From the parent agent perspective:

1. It calls `tool_subagent`.
2. It stops receiving tokens for that turn while child agents work.
3. It later receives one tool result containing all child results.
4. It continues reasoning from that tool result.
5. It can answer the user, call more tools, or launch another subagent run.

The child agent sees only its assigned task and child tool list.

From the child agent perspective:

1. It receives an initial task prompt.
2. It may call allowed child tools.
3. It must end by calling `tool_return_to_parent`.
4. It cannot launch further subagents unless nested subagents are explicitly added later.

The parent agent should receive failed child results as data it can reason about. A failed child is not hidden from the parent.

## Backend API Shape

Existing APIs can support most reads:

- `/api/conversation/list` with no `parentId` returns root conversations.
- `/api/conversation/list` with `parentId = parentConversationId` returns children.
- `/api/conversation/list` with `parentId = *` can refresh a broad local cache.
- `/api/event/list` reads parent or child events.

Useful additions:

- child summary endpoint for one parent run, if repeated event-list reads become too heavy
- backend helper to mark parent `TOOL_RESULT_READY` after child terminal state
- worker iteration branch for `TEMPLATE_START_READY`
- worker iteration branch for `TOOL_RESULT_READY`
- version-checked progress commit for child events

The API layer should answer quickly. Long model calls, child execution, parent resume, and retry behavior belong to scheduler-owned tasks.

