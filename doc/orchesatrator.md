# Orchestrator And Orchestration

## Scope

An orchestrator is the transition logic for a conversation.

A conversation stores durable state: metadata plus an ordered event list. The orchestrator reads that state, runs one iteration, and returns new event dictionaries. Backend code persists those events and updates conversation metadata.

This document covers the concept of orchestrator and orchestrator instances(also called templates), and how to use orchestrator to interate a conversation. `doc/conversation.md` covers event meaning and storage rules. `doc/conversation-iter-task.md` covers leases, workers, retries, and scheduler behavior.

## Core Model

One conversation is one multi-turn interaction with an agent. It is rolled out by repeatedly iterating the orchestrator selected by `conversation.metadata.templateKey`.

Template configuration lives in `config/templates.py`. Template module loading lives in `backend/conifg_template.py`.

Current templates:

| Key | User visible | Implementation |
| --- | --- | --- |
| `free-talk` | yes | built into `backend/iteration_executor.py` |
| `web-fetch-local` | yes | `test/_0_web_fetch_local/orchestrator.py` |
| `mcp-tool-all` | yes | `test/_1_mcp/orchestrator.py` |
| `mcp-interactive` | yes | `test/_1_mcp/orchestrator.py` |
| `subagent-basic` | no | `test/_2_sub_agent/orchestrator_subagent.py` |

The template key is durable conversation metadata. The orchestrator module should not create another source of truth for event order, user-turn state, or completion state.

## Iteration Interface

`backend/iteration_executor.py` is the common entry point:

```text
run_orchestrator(context)
  create_orchestrator_state(context)
  iter_orchestrator(state)
```

Important context fields:

| Field | Meaning |
| --- | --- |
| `templateKey` | selects the orchestrator |
| `iterType` | entry point, usually `templateStart` or `userMessage` |
| `conversationId` | conversation being iterated |
| `messageText` | latest user text for user-message iteration |
| `eventList` | loaded event history in conversation order |
| `initialPrompt` | internal subagent startup task |
| `maxTurns` | internal subagent turn limit |
| `backendToolList` | backend-owned tools exposed to template code |
| `executeBackendTool` | callback for backend-owned tool execution |

The orchestrator returns an iterator of event dictionaries. The backend writes each item as an event row and appends its ID to `conversation.metadata.eventList`.

`iter_orchestrator(state)` branches by current state:

| Condition | Action |
| --- | --- |
| `iterType == templateStart` | call the selected template module without a user message |
| `templateKey == free-talk` | build a plain prompt from text events and call the model |
| otherwise | call the selected template module with event history and latest user message |

## User Message Process

User-entered turns now use the task-driven backend path.

For `/api/orchestrator/turn/create`:

1. Validate that the conversation can accept user input.
2. Append `userMessage / textSimple`.
3. Set `metadata.isUserTurn = false`.
4. Set `stateCode = USER_MESSAGE_READY` and `execStatusCode = PENDING`.
5. Notify `conversation_task_ready`.
6. Return the accepted user event with `isScheduled = true`.
7. A scheduler leases the conversation to a worker.
8. The worker loads events, runs one orchestrator iteration, and commits generated events.
9. The worker sets the next state, usually `WAIT_USER` or `COMPLETED`.

The route does not return an agent reply. The frontend refreshes events from the API after update notifications and quiet polling.

## Template Startup Process

`POST /api/conversation/create/from-template` creates the conversation and may run a `templateStart` iteration.

Templates with `isStartBackground = true` still use the older daemon-thread startup path:

1. Create the conversation with template metadata.
2. Start `templateStart`.
3. Write the first generated event before returning when available.
4. Continue writing remaining startup events in the background.
5. Apply `metadataStartFinish` when startup finishes.

This startup path is separate from the task-driven user-message worker path.

## Built-In Free Talk

`free-talk` is implemented in `backend/iteration_executor.py`.

It reads prior `textSimple` events and converts them into a plain prompt:

| Event source | Prompt text |
| --- | --- |
| `userMessage` | `User:` |
| `agentMessage` | `Assistant:` |
| `orchestratorMessage` | `Orchestrator:` |

It then yields one `agentMessage / textSimple` event.

## Web Fetch Local

`web-fetch-local` lives in `test/_0_web_fetch_local/orchestrator.py`.

It converts event history into a simple dialogue, fetches live page text through the experiment helper, asks the model to answer from fetched text, and yields one `agentMessage / textSimple` event with debug metadata.

## MCP Tool Templates

`mcp-tool-all` and `mcp-interactive` share `test/_1_mcp/orchestrator.py`.

The template module rebuilds model messages from events. `agentMessage` events become assistant messages; other text events become user-side messages.

The tool loop:

1. Yield an initial `orchestratorMessage / textSimple` prompt if no initial prompt exists.
2. Ask the model for a reply.
3. Parse the reply as a tool call when the current mode requires one.
4. If parsing fails in exercise mode, yield an agent rejection event and an orchestrator retry instruction.
5. If the reply is accepted as natural text in interactive mode, yield `agentMessage / textSimple` and stop the iteration.
6. If parsing succeeds, yield `agentMessage / toolCall`.
7. Execute the tool or backend-owned tool.
8. Yield `orchestratorMessage / toolResult`.
9. Continue until the loop is complete or the loop limit is reached.

`mcp-tool-all` is a one-shot exercise. It does not accept user messages and finishes as completed after startup.

`mcp-interactive` starts with the same exercise. Later user-message iterations switch to interactive mode: natural-language replies are allowed, repeated tools are allowed, and `tool_terminate_conversation` can end the conversation.

## Subagents

Subagents are currently exposed as the backend-owned tool `tool_subagent`.

When the parent orchestrator calls it, the task-driven flow is:

1. Append the parent `agentMessage / toolCall` request.
2. Set the parent to `SUBAGENT_LAUNCH_READY`.
3. In a later worker task, create child conversations with `parentId` pointing at the parent.
4. Append `orchestratorMessage / subAgentStart` in the parent.
5. Set the parent to `WAIT_SUBAGENT`.
6. Run each child conversation as independent scheduled work.
7. When the last child reaches terminal state, append `orchestratorMessage / subAgentResult` in the parent and set the parent to `TOOL_RESULT_READY`.

Each child uses `test/_2_sub_agent/orchestrator_subagent.py`. A child must end by calling `tool_return_to_parent`, which yields `orchestratorMessage / subAgentReturn` in the child conversation.

The detailed state and database design is in `doc/subagent.md`.

## Event Ownership

The orchestrator decides what generated events mean. The backend owns durable writes.

| Event | Created by | Meaning |
| --- | --- | --- |
| `userMessage / textSimple` | backend route | user input was accepted |
| `agentMessage / textSimple` | orchestrator | model answered naturally |
| `agentMessage / toolCall` | orchestrator | model requested a tool |
| `orchestratorMessage / textSimple` | orchestrator or backend | instruction, retry, startup prompt, or status text |
| `orchestratorMessage / toolResult` | orchestrator | tool result returned to the agent loop |
| `orchestratorMessage / subAgentStart` | backend tool | child conversations were started |
| `orchestratorMessage / subAgentResult` | backend tool | child conversations returned to parent |
| `orchestratorMessage / subAgentReturn` | child orchestrator | child returned to parent |
| `EndAbnormal / BackendException` | backend | backend could not continue safely |

If orchestration fails after a conversation exists, the backend appends `EndAbnormal / BackendException`, sets `statusText = failed`, sets `isUserTurn = false`, and records `endStatusText = abnormal`.

## Relationship To Task Iteration

`doc/conversation-iter-task.md` describes how an iteration is scheduled and committed. This document describes what the iteration does.

The important boundary is ownership:

| Layer | Owns |
| --- | --- |
| conversation model | durable event list and metadata |
| orchestrator | generated event sequence for one iteration |
| task worker | lease, execution attempt, commit, retry, and failure handling |
| database | final authorization through `version`, `leaseId`, `leaseWorkerId`, and `leaseExpireAt` |

That boundary lets the backend move toward stateless workers without changing the template interface.
