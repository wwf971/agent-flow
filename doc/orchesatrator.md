# Orchestrator And Orchestration

## Scope

An orchestrator decides how a conversation advances.

The conversation itself is only an ordered event list plus metadata. The orchestrator reads the current conversation state, runs one iteration, and produces zero or more new events. Those events are appended to the same conversation timeline.

This document owns the orchestration concept: how an orchestrator is selected, what input it receives, and how it produces events. `doc/conversation.md` owns event meaning and conversation state. `doc/agent-flow.md` is the root guide.

## Core Idea

One conversation is one multi-turn interaction with an agent. It is rolled out by repeatedly iterating the orchestrator associated with that conversation.

The orchestrator is selected by `conversation.metadata.templateKey`.

Template keys:

| Key | User visible | Orchestrator |
| --- | --- | --- |
| `free-talk` | yes | built into `backend/iteration_executor.py` |
| `web-fetch-local` | yes | `test/_0_web_fetch_local/orchestrator.py` |
| `mcp-tool-all` | yes | `test/_1_mcp/orchestrator.py` |
| `mcp-interactive` | yes | `test/_1_mcp/orchestrator.py` |
| `subagent-basic` | no | `test/_2_sub_agent/orchestrator_subagent.py` |

Template configuration lives in `config/templates.py`. Template module loading lives in `backend/conifg_template.py`.

## Relationship To Conversation

The conversation is durable state. The orchestrator is transition logic.

The orchestrator must not create a second source of truth for event order, user-turn state, or completion state. It reads the conversation event list and metadata, then returns event dictionaries. Backend code persists the events and related metadata changes.

The event field schema and content type rules are defined in `doc/conversation.md`. This document only uses event names to explain orchestration flow.

## Iteration Input

The backend uses a small context object to call an orchestrator. Important fields are:

| Field | Meaning |
| --- | --- |
| `templateKey` | selects the conversation orchestrator |
| `iterType` | coarse iteration entry point, such as `templateStart` or `userMessage` |
| `conversationId` | conversation being iterated |
| `messageText` | latest user message for a user-message iteration |
| `eventList` | loaded event history in conversation order |
| `initialPrompt` | startup prompt used by internal subagent conversations |
| `maxTurns` | maximum turns for internal subagent loops |
| `backendToolList` | backend tools exposed to a template orchestrator |
| `executeBackendTool` | callback used by template orchestrators to run backend-owned tools |

The orchestrator returns an iterator of event dictionaries. Each yielded item is written as an event row by the backend.

## Iteration Branch

`backend/iteration_executor.py` is the orchestrator entry point.

```text
run_orchestrator(context)
  create_orchestrator_state(context)
  iter_orchestrator(state)
```

`iter_orchestrator(state)` branches like this:

| Condition | Action |
| --- | --- |
| `iterType == templateStart` | call the selected template module with no user message |
| `templateKey == free-talk` | build a plain text prompt from text events and call the model |
| otherwise | call the selected template module with event history and latest user message |

The backend persists generated events outside the template module. This keeps the template interface small: template code decides what events should happen next, while backend code owns database writes.

## Task-Driven Process

The current backend accepts user input synchronously, then schedules orchestration as durable database work.

For `/api/orchestrator/turn/create`:

1. Validate that the conversation accepts user input.
2. Append the `userMessage / textSimple` event.
3. Set `conversation.metadata.isUserTurn = false`.
4. Set `stateCode = USER_MESSAGE_READY` and `execStatusCode = PENDING`.
5. Notify `conversation_task_ready`.
6. Return the accepted user event immediately with `isScheduled = true`.
7. A scheduler leases the conversation to an idle worker.
8. The worker loads the event list, runs one orchestrator iteration, and commits generated events.
9. The worker updates metadata and returns the conversation to `WAIT_USER`, `COMPLETED`, or another scheduler-visible state.

The route does not return an agent reply directly. The frontend should refresh events from the API after update notifications or quiet polling.

For a normal `free-talk` turn, the worker calls the built-in orchestrator and appends one `agentMessage / textSimple` event. For template turns, the worker calls the selected template module and appends each yielded event.

`doc/conversation-iter-task.md` owns scheduler, worker, lease, retry, and restart behavior.

## Legacy Thread-Based Process

The thread-based backend runs template creation and user turns in background threads. The request stores accepted input quickly. Generated events are appended by the background runner.

For `/api/conversation/create/from-template`:

1. Create the conversation with template metadata.
2. If the template starts in the background, run `templateStart`.
3. Write the first generated event before returning when available.
4. Continue writing remaining generated events in a daemon thread.
5. Apply the template finish metadata when startup finishes.

For `/api/orchestrator/turn/create`:

1. Validate that the conversation accepts user input.
2. Set `isUserTurn = false`.
3. Append the `userMessage / textSimple` event.
4. Return immediately with the user event and no generated events.
5. Run the selected orchestrator in a daemon thread.
6. Append each generated event as it is yielded.
7. Apply finish metadata, usually `isUserTurn = true`, unless the conversation completed or failed.

If a backend exception happens after a conversation exists, the backend appends `EndAbnormal / BackendException`, sets `statusText = failed`, sets `isUserTurn = false`, and records `endStatusText = abnormal`.

This path is still useful for understanding older code and template startup behavior, but user-message iteration is now routed through the task-driven worker path.

## Orchestrator Types

### Free Talk

`free-talk` is built into `backend/iteration_executor.py`.

It reads previous `textSimple` events and converts them to a plain prompt:

| Event source | Prompt line |
| --- | --- |
| `userMessage` | `User:` |
| `agentMessage` | `Assistant:` |
| `orchestratorMessage` | `Orchestrator:` |

It then appends one `agentMessage / textSimple` event.

### Web Fetch Local

`web-fetch-local` lives in `test/_0_web_fetch_local/orchestrator.py`.

It converts the event history into a simple dialogue, fetches live page text through the experiment helper, asks the model to answer from fetched text, and yields one `agentMessage / textSimple` event with debug metadata.

### MCP Tool Templates

`mcp-tool-all` and `mcp-interactive` share `test/_1_mcp/orchestrator.py`.

The orchestrator starts by yielding an `orchestratorMessage / textSimple` startup prompt. Then it loops:

1. Ask the agent for a response.
2. Parse the response as a tool call.
3. If parsing fails, append an agent rejection event and an orchestrator retry instruction.
4. If parsing succeeds, append `agentMessage / toolCall`.
5. Execute the tool.
6. Append `orchestratorMessage / toolResult`.
7. Continue until the mode is complete or the loop limit is reached.

`mcp-tool-all` is a one-shot exercise. It does not accept user messages and finishes as completed.

`mcp-interactive` starts with the same exercise. After startup has produced the initial prompt, later user-message iterations switch to interactive mode: natural-language replies are allowed, repeated tools are allowed, and `tool_terminate_conversation` is available when the user wants to end the conversation.

### Subagent Tool

The thread-based backend supports subagents through a backend-owned tool.

The parent orchestrator can call the backend tool `tool_subagent`. The backend then:

1. Creates child conversations with `parentId` pointing at the parent.
2. Appends `orchestratorMessage / subAgentStart` in the parent.
3. Runs each child conversation in a thread using the internal `subagent-basic` template.
4. Waits for child results.
5. Appends `orchestratorMessage / subAgentResult` in the parent.

Each child uses `test/_2_sub_agent/orchestrator_subagent.py`. A child must eventually call `tool_return_to_parent`, which produces `orchestratorMessage / subAgentReturn` in the child conversation.

In the task-based design, child work should be explicit scheduler work instead of hidden work inside a parent process.

## Event Ownership

The orchestrator decides event semantics. The backend owns persistence.

Use these rules:

| Event | Created by | Meaning |
| --- | --- | --- |
| `userMessage / textSimple` | backend route | user input was accepted |
| `agentMessage / textSimple` | orchestrator | model answered naturally |
| `agentMessage / toolCall` | orchestrator | model requested tool execution |
| `orchestratorMessage / textSimple` | orchestrator or backend | instruction, retry, startup prompt, or status text |
| `orchestratorMessage / toolResult` | orchestrator | tool result returned to the agent loop |
| `orchestratorMessage / subAgentStart` | backend tool | child conversations were started |
| `orchestratorMessage / subAgentResult` | backend tool | child conversations returned to parent |
| `orchestratorMessage / subAgentReturn` | child orchestrator | child returned to parent |
| `EndAbnormal / BackendException` | backend | backend could not continue safely |

## Task-Based Process

`doc/conversation-iter-task.md` describes the task-based orchestration process.

The main change is ownership. A process should not own a conversation because it has a thread running. A worker should own only one leased iteration, and the database should authorize the final write through `version`, `leaseId`, `leaseWorkerId`, and `leaseExpireAt`.

With this design, subagents become normal scheduled child conversations. Parent and child progress can be parallelized across stateless worker containers.