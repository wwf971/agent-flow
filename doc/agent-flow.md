# Agent Flow

## Scope

This is the root guide for the project documents.

The system stores each agent interaction as a conversation. A conversation is durable state. An orchestrator reads that state and decides the next events. Backend services expose APIs, persist events, and run orchestration work.

## Core Architecture

```text
frontend or script
  -> HTTP API
  -> backend service
  -> conversation and event storage
  -> orchestrator
  -> model and tools
  -> new events
  -> conversation update notification
```

The database is the source of truth. WebSocket and PostgreSQL notify are refresh hints. API reads are used to get durable state.

## Main Concepts

| Concept | Meaning | Source of truth |
| --- | --- | --- |
| conversation | one multi-turn interaction with an agent | `conversation` row |
| event | one timeline item in a conversation | `event` row |
| event order | order of events in one conversation | `conversation.metadata.eventList` |
| orchestrator | logic that decides next events | template key and orchestrator code |
| template | named orchestrator mode | `config/templates.py` |
| backend task | long-running orchestration work | leased worker design |

## Document Map

| Document | Topic |
| --- | --- |
| `doc/conversation.md` | Conversation and event model. It defines durable state and event meanings. |
| `doc/orchesatrator.md` | Orchestrator model. It defines how conversation state is turned into new events. |
| `doc/backend.md` | Backend modules and request/task logic. |
| `doc/api.md` | HTTP routes, request shape, response shape, and error codes. |
| `doc/database.md` | Database tables, IDs, indexes, and notifications. |
| `doc/conversation-iter-task.md` | Task-driven iteration with leases and workers. |

## Conversation And Orchestrator

`doc/conversation.md` and `doc/orchesatrator.md` describe the same system from two sides.

`doc/conversation.md` answers:

- what a conversation is
- what an event is
- how event order is stored
- what event types mean
- what metadata controls user-visible state

`doc/orchesatrator.md` answers:

- how an orchestrator is selected
- what input an orchestrator receives
- how one iteration produces events
- how template modes differ
- how tools and subagents are driven

The boundary is simple: conversation is state; orchestrator is transition. The conversation document should not explain template branching or model/tool loops. The orchestrator document should not redefine database columns or full event field schemas.

## Backend Logic

Quick API logic should accept or reject requests quickly and write durable state in a transaction.

Long work should be represented as a task. A task may call models, execute tools, or wait for subagents. Task results become new events, then conversation metadata is updated.

User-message iteration uses the task-driven worker design. Template startup can still use the older thread path. Both execution forms follow the same model:

- read conversation state
- run one orchestrator iteration
- append generated events
- update conversation metadata
- notify clients to refresh

## Key Files

| File | Responsibility |
| --- | --- |
| `backend/iteration_scheduler.py` | Decides when work runs, leases conversation rows, owns worker loops, retries real worker errors, and commits results. |
| `backend/iteration_executor.py` | Executes one iteration by choosing template or orchestrator logic and yielding events. |
| `backend/conversation.py` | Owns conversation APIs, metadata updates, list/read helpers, and conversation row formatting. |
| `backend/event.py` | Owns event APIs and appends events to `conversation.metadata.eventList`. |
| `backend/conifg_template.py` | Loads template definitions and calls template `orchestrator_iter(context)` functions. |
| `config/templates.py` | Defines user-visible templates and their module paths. |
| `database/init_table.sql` | Defines the executable PostgreSQL schema. |
| `frontend/src/store/appStore.ts` | Owns frontend state, API refresh, WebSocket refresh hints, and pending-message state. |

## Reading Order

Start with this document, then read:

1. `doc/conversation.md`
2. `doc/orchesatrator.md`
3. `doc/backend.md`
4. `doc/api.md`
5. `doc/database.md`
6. `doc/conversation-iter-task.md`