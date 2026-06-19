# Backend Design

## Goal

The backend manages conversations and ordered events. Agent orchestration sits on top of that storage model, instead of mixing long terminal logs with model calls.

The backend stays small:

- PostgreSQL storage for `conversation` and `event`
- Flask HTTP API following `code/data/message`
- small login/token authorization layer with `R` and `W` permissions
- template creation and user-turn endpoints backed by `backend/iteration_executor.py`
- task-driven conversation iteration backed by `backend/iteration_scheduler.py`
- content type mapping loaded from YAML config

Database details are in `doc/database.md`. Endpoint details are in `doc/api.md`. Orchestration concepts and templates are in `doc/orchesatrator.md`.

## Runtime Shape

```text
frontend or script
  -> HTTP API
  -> conversation service
  -> event service
  -> orchestrator service
  -> model/tool adapters
  -> PostgreSQL
```

External model calls go through `api_llm`, and the persisted event model is the stable boundary. Template orchestrators can reuse experiment code under `test/`.

## Backend Modules

Main files:

```text
backend/app.py
backend/config.py
backend/db.py
backend/login.py
backend/id_service.py
backend/conversation.py
backend/event.py
backend/iteration_executor.py
backend/iteration_scheduler.py
database/init_table.sql
config/conversation_content_type.yaml
config/templates.py
```

Responsibilities:

| File | Responsibility |
|------|----------------|
| `app.py` | Flask app setup and route registration |
| `config.py` | config loading and constants |
| `db.py` | database connection and transaction helper |
| `login.py` | login, token storage, and permission checks |
| `id_service.py` | `ms_48` ID allocation |
| `conversation.py` | conversation endpoints and service logic |
| `event.py` | event endpoints and service logic |
| `iteration_executor.py` | orchestrator entry point, template creation, turn creation route, and backend tools |
| `iteration_scheduler.py` | task scheduler, worker runtime, leases, retry, and iteration commits |
| `config/templates.py` | template metadata and module paths |

## Orchestrator Flow

The durable storage boundary is the conversation event list. The user-message route accepts input quickly, marks the conversation as needing iteration, and returns before generated events exist.

For `POST /api/orchestrator/turn/create`:

1. Validate request and conversation state.
2. Create conversation when `conversationId` is absent.
3. Append `userMessage/textSimple` event.
4. Set `isUserTurn = false`, `stateCode = USER_MESSAGE_READY`, and `execStatusCode = PENDING`.
5. Notify `conversation_task_ready`.
6. Return the accepted user event immediately with `isScheduled = true`.
7. A worker leases the conversation, runs one orchestrator iteration, appends generated events, and commits the next state.

For `POST /api/conversation/create/from-template`, the backend creates the conversation and may start a `templateStart` iteration. Templates marked `isStartBackground` still use the older background-thread startup path.

If orchestration fails after a conversation exists, append `EndAbnormal/BackendException`, set `statusText = failed`, set `isUserTurn = false`, and record `endStatusText = abnormal`.

Each event append must insert the event row and update `conversation.metadata.eventList` in one transaction.

Orchestration concepts are in `doc/orchesatrator.md`. Task scheduler and worker details are in `doc/conversation-iter-task.md`.

Normal startup creates missing schema only. It does not reinitialize an existing database.

## Event Types

The storage model supports multiple event values without adding new tables:

| typeText | subtypeText | Notes |
|----------|-------------|-------|
| `agentMessage` | `toolCall` | model requests tool execution |
| `orchestratorMessage` | `toolResult` | tool result sent back to agent |
| `userMessage` | `textWithFile` | user text with file reference metadata |
| `userMessage` | `textWithImage` | user text with image reference metadata |
| `orchestratorMessage` | `subAgentStart` | subagent created |
| `orchestratorMessage` | `subAgentResult` | subagent result received |
| `orchestratorMessage` | `subAgentReturn` | child conversation returned to parent |

For `orchestratorMessage/toolResult`, the backend should keep `contentText` as the exact text that was sent back into the model context. `contentJson` may store a structured segment envelope for frontend display. This lets the UI abbreviate long fields such as fetched web page text without changing the agent-facing message.

## Frontend Direction

React state should be store-driven:

- store owns conversation list, current conversation, events, and request state
- render components receive data and send change attempts through store methods
- no component should call backend endpoints directly
- editable text areas should avoid height or width jitter when entering edit mode
