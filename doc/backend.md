# Backend Design

## Goal

The backend should first manage conversations and ordered events. Agent orchestration should sit on top of that storage model, instead of mixing long terminal logs with model calls.

The first useful backend can stay small:

- PostgreSQL storage for `conversation` and `event`
- Flask HTTP API following `code/data/message`
- small login/token authorization layer with `R` and `W` permissions
- one orchestrator endpoint for pure text conversation
- content type mapping loaded from YAML config

Database details are in `doc/database.md`. Endpoint details are in `doc/api.md`.

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

For the first version, model/tool adapters can reuse the current experiment code from `test_genai.py`, `test/_0_web_fetch_local/test.py`, and `test/_1_mcp/test.py` only where it helps. The persisted event model should be the new stable boundary.

## Backend Modules

Suggested files:

```text
backend/app.py
backend/config.py
backend/db.py
backend/login.py
backend/id_service.py
backend/conversation.py
backend/event.py
backend/orchestrator.py
database/init_table.sql
config/conversation_content_type.yaml
script/reinit_database.py
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
| `orchestrator.py` | text turn creation and model call flow |

## Orchestrator Flow

For `POST /api/orchestrator/turn/create`:

1. Validate request.
2. Create conversation when `conversationId` is absent.
3. Append `userMessage/textSimple` event.
4. Read conversation IDs from `conversation.metadata.evetList`.
5. Build model context from supported text events.
6. Call model.
7. Append `agentMessage/textSimple` event.
8. Return the new conversation ID and event IDs.

If the model call fails after the user event has been written, append an `orchestratorMessage/textSimple` event describing the failure and return a negative `code`.

Each event append must insert the event row and update `conversation.metadata.evetList` in one transaction.

## Future Event Types

The storage model should later support more event values without adding new tables:

| typeText | subtypeText | Notes |
|----------|-------------|-------|
| `agentMessage` | `toolCall` | model requests tool execution |
| `orchestratorMessage` | `toolResult` | tool result sent back to agent |
| `userMessage` | `textWithFile` | user text with file reference metadata |
| `userMessage` | `textWithImage` | user text with image reference metadata |
| `orchestratorMessage` | `subAgentStart` | sub-agent created |
| `orchestratorMessage` | `subAgentResult` | sub-agent result received |

Those are not first-version requirements. The first version should only implement `textSimple`.

For `orchestratorMessage/toolResult`, the backend should keep `contentText` as the exact text that was sent back into the model context. `contentJson` may store a structured segment envelope for frontend display. This lets the UI abbreviate long fields such as fetched web page text without changing the agent-facing message.

## Frontend Direction

When UI is added, React state should be store-driven:

- store owns conversation list, current conversation, events, and request state
- render components receive data and send change attempts through store methods
- no component should call backend endpoints directly
- editable text areas should avoid height or width jitter when entering edit mode
