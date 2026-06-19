# Database Implementation

## Scope

This document covers lower-level database storage details for the conversation model. The semantic conversation and event model is documented in `doc/conversation.md`.

## ID Format

All primary IDs use `ms_48`.

`ms_48` is a 64-bit integer:

```text
high |-------48bit------|---16bit---| low
high |---unix_stamp_ms--|---offset--| low
```

Database columns store it as `bigint`. API responses return IDs as strings to avoid JavaScript integer precision loss.

Columns:

- `conversation.id`: `bigint`
- `conversation.parentId`: `bigint`
- `event.id`: `bigint`
- `event.conversationId`: `bigint`

## Time Format

Timestamp columns use `timestamptz`. Timezone columns use signed integer minutes.

Examples:

- Tokyo: `540`
- UTC: `0`
- New York standard time: `-300`

Table columns use:

- `createAt`
- `createAtTimezone`
- `updateAt`
- `updateAtTimezone`

For display and log file names, the preferred text format remains `20260520_23250530+09`.

## Table: `conversation`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `bigint` PK | `ms_48` ID |
| `metadata` | `jsonb` | flexible metadata object, must include `eventList` |
| `isInTrashbin` | `boolean` | default `false` |
| `rankGlobal` | `text` | top-level conversation ordering key |
| `parentId` | `bigint` | optional parent conversation for subagent conversations |
| `version` | `bigint` | semantic version used by worker commit checks |
| `stateCode` | `integer` | semantic conversation state for iteration |
| `execStatusCode` | `integer` | scheduler ownership state |
| `leaseId` | `text` | current worker lease |
| `leaseWorkerId` | `text` | worker that owns the current lease |
| `leaseExpireAt` | `timestamptz` | time when a running lease expires |
| `leaseRetryCount` | `integer` | worker-owned retry count for real iteration errors |
| `leaseRetryAfterAt` | `timestamptz` | earliest retry time after a worker-owned error |
| `createAt` | `timestamptz` | default `now()` |
| `createAtTimezone` | `smallint` | signed minutes |
| `updateAt` | `timestamptz` | default `now()` |
| `updateAtTimezone` | `smallint` | signed minutes |

The backend should always normalize `metadata.eventList` and `metadata.childConversationIdList` as string arrays before writing.

Indexes:

```sql
create index conversation_update_at_idx
  on conversation(updateAt desc, id desc);

create index conversation_rank_global_idx
  on conversation(isInTrashbin, rankGlobal, updateAt desc, id desc)
  where parentId is null;

create index conversation_parent_idx
  on conversation(parentId, updateAt desc, id desc);

create index conversation_iter_pending_idx
  on conversation(stateCode, execStatusCode, leaseExpireAt, leaseRetryAfterAt, id)
  where stateCode < 0;

create index conversation_lease_expire_idx
  on conversation(leaseExpireAt, id)
  where leaseId is not null;
```

The meaning of iteration state and lease columns is documented in `doc/conversation-iter-task.md`.

## Table: `conversation_iter_worker`

| Column | Type | Notes |
|--------|------|-------|
| `workerId` | `text` PK | stable worker identity |
| `conversationId` | `bigint` | assigned conversation, null when idle |
| `leaseId` | `text` | assigned lease, null when idle |
| `assignAt` | `timestamptz` | assignment time |
| `heartbeatAt` | `timestamptz` | worker liveness time |
| `updateAt` | `timestamptz` | row update time |
| `workerProcessId` | `integer` | local process id for tracing |
| `workerHostText` | `text` | host or container name for tracing |
| `workerStartAt` | `timestamptz` | worker registration time |

Indexes:

```sql
create index conversation_iter_worker_idle_idx
  on conversation_iter_worker(heartbeatAt, workerId)
  where conversationId is null;
```

## Table: `event`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `bigint` PK | `ms_48` ID |
| `conversationId` | `bigint` FK | references `conversation(id)` |
| `typeCode` | `integer` | nullable during development |
| `typeText` | `text` | development-friendly event type |
| `subtypeCode` | `integer` | nullable during development |
| `subtypeText` | `text` | development-friendly subtype |
| `contentType` | `integer` | maps to config file |
| `contentText` | `text` | nullable |
| `contentJson` | `jsonb` | nullable |
| `metadata` | `jsonb` | optional event metadata |
| `createAt` | `timestamptz` | default `now()` |
| `createAtTimezone` | `smallint` | signed minutes |
| `updateAt` | `timestamptz` | default `now()` |
| `updateAtTimezone` | `smallint` | signed minutes |

Event order is not stored in the event row. Event order is stored in `conversation.metadata.eventList`.

Indexes:

```sql
create index event_conversation_create_at_idx
  on event(conversationId, createAt, id);

create index event_type_text_idx
  on event(typeText, subtypeText);
```

## Content Type Config

`contentType` is resolved through:

```text
config/conversation_content_type.yaml
```

Current content:

```yaml
contentTypeByCode:
  1:
    name: text
    activeColumn: contentText
  2:
    name: json
    activeColumn: contentJson
  3:
    name: textWithJson
    activeColumn: contentTextAndContentJson
```

## Notification Trigger

The database uses `pg_notify` on the `conversation_update` channel after conversation or event changes.

Notification fields:

- `typeText`: `conversationUpdate`
- `tableText`: changed table
- `operationText`: SQL operation
- `conversationId`: changed conversation ID

When a child conversation or child event changes, the trigger also notifies the parent conversation ID. PostgreSQL delivers notifications after transaction commit.

If multiple events are inserted in one transaction, clients receive them only after that transaction finishes.

## SQL Draft

The executable schema is in `database/init_table.sql`.

## Reinitialize Database

Reinitialization is destructive. `database/init_table.sql` drops and recreates conversation tables, so existing conversations and events are removed.

Manual reinitialization can be run through `script/_1_reinit_database.py`, by applying `database/init_table.sql`, or through the backend endpoint:

```text
POST /api/service/database/reinit
```

This endpoint requires write permission. Normal service startup and normal deploy should call schema bootstrap only; they should not reinitialize the database.
