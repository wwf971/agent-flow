# Conversation Iteration Task Design

This document describes task-driven conversation iteration for stateless workers and deployment-friendly parallel execution.

For orchestration concepts and template behavior, see `doc/orchesatrator.md`.

## Core Design

The database owns conversation iteration state.

A backend process does not own a conversation because it has a thread or an in-memory object. It owns one iteration only when the database row has a matching lease. The lease is checked again before writing results. If the check fails, the iteration result is discarded.

This gives the system three stable layers:

- `conversation`: durable semantic state, scheduler state, and lease state.
- `conversation_iter_worker`: worker liveness and dispatch state.
- PostgreSQL `notify`: wake-up signal only.

The basic runtime pattern is poll plus listen. Scheduler and worker logic always polls database state. PostgreSQL `notify` only wakes the loop earlier.

The frontend receives updates through WebSocket, but the frontend also refreshes from APIs. WebSocket messages are refresh hints, not durable state.

## Source Of Truth

`conversation` is the source of truth for one conversation.

`event` stores timeline items, but event order is still owned by `conversation.metadata.eventList`.

`conversation_iter_worker` is not source of truth. It only tells a worker which leased conversation to poll next. A stale worker row cannot authorize writes. Only the lease fields on `conversation` can authorize writes.

PostgreSQL `notify` is not source of truth. If a notification is lost, a later poll must still find the same conversation needing work or the same worker assignment.

## Conversation Table Columns

The `conversation` row naturally contains the information for whether the conversation needs immediate iteration.

| Column | Type | Use |
| --- | --- | --- |
| `version` | bigint not null default 0 | Concurrency guard for semantic commits. It increments when conversation meaning changes. |
| `stateCode` | integer not null default 100 | Semantic state after the latest committed version. Negative values mean automated iteration is needed. |
| `execStatusCode` | integer not null default 0 | Scheduler state for the current semantic state. |
| `leaseId` | text | Current lease id. Null means no active lease. |
| `leaseWorkerId` | text | Worker id that owns the current lease. Null means no worker owns it. |
| `leaseExpireAt` | timestamptz | Lease expiration time. Expiry is abnormal and is not retried. |
| `leaseRetryCount` | integer not null default 0 | Worker-owned retry count for real iteration errors. |
| `leaseRetryAfterAt` | timestamptz | Earliest retry time after a worker-owned iteration error. |

Existing rows can start with:

```sql
version = 0
stateCode = 100
execStatusCode = 0
leaseId = null
leaseWorkerId = null
leaseExpireAt = null
leaseRetryCount = 0
leaseRetryAfterAt = null
```

`version` increments when committed conversation meaning changes, such as user input, generated events, completed state, or failed state. Scheduler lease claim, lease refresh, worker heartbeat, and worker assignment do not increment `version`.

When a new pending semantic state is created, retry columns reset to their empty values.

Useful indexes:

```sql
create index conversation_iter_pending_idx
  on conversation(stateCode, execStatusCode, leaseExpireAt, leaseRetryAfterAt, id)
  where stateCode < 0;

create index conversation_lease_expire_idx
  on conversation(leaseExpireAt, id)
  where leaseId is not null;
```

### State Code

`stateCode` describes what the conversation means after the latest committed version.

Negative values mean the scheduler should inspect the row. Positive values mean no immediate automated iteration is needed.

Current worker execution primarily uses `USER_MESSAGE_READY` for user-message iteration. Subagent support should add explicit scheduler states for launch initialization, child template startup, child waiting, and parent continuation.

| Code | Name | Meaning |
| --- | --- | --- |
| `-400` | `TEMPLATE_START_READY` | Template startup should run as a task. Subagent child startup uses this. |
| `-300` | `SUBAGENT_LAUNCH_READY` | Parent has a `tool_subagent` request event and child conversations should be initialized. |
| `-200` | `TOOL_RESULT_READY` | Tool or subagent result is ready and agent should continue. |
| `-100` | `USER_MESSAGE_READY` | User message is committed and agent should run. |
| `100` | `WAIT_USER` | Conversation waits for user input. |
| `200` | `COMPLETED` | Conversation ended normally. |
| `300` | `ARCHIVED` | Conversation is archived. |
| `400` | `WAIT_SUBAGENT` | Parent conversation waits for child conversations. No immediate parent iteration is needed. |
| `1000` | `FAILED` | Conversation ended abnormally. Scheduler must stop. |

### Exec Status Code

`execStatusCode` describes scheduler ownership, not conversation meaning.

| Code | Name | Meaning |
| --- | --- | --- |
| `0` | `IDLE` | No lease and no scheduler action queued. |
| `10` | `PENDING` | Scheduler can try to assign work. |
| `20` | `RUNNING` | A worker owns a non-expired lease. |
| `30` | `RETRY_WAIT` | A worker caught a real iteration error and asked scheduler to retry later. |

`stateCode` and `execStatusCode` are separate because a conversation may keep the same semantic state while a lease is claimed and refreshed.

### Immediate Iteration Row

A row needs immediate iteration when:

- `stateCode < 0`
- `execStatusCode in (IDLE, PENDING, RETRY_WAIT)`
- no active lease
- `leaseRetryAfterAt is null`, or `leaseRetryAfterAt <= now()`

User input is one example of creating such a row:

```text
insert userMessage event
append event id to metadata.eventList
stateCode = USER_MESSAGE_READY
execStatusCode = PENDING
version += 1
leaseRetryCount = 0
leaseRetryAfterAt = null
notify conversation_task_ready
```

The notify call belongs in the same transaction as the state change. PostgreSQL sends it only after commit. If notify is missed, scheduler polling still finds the row.

## Scheduler

The scheduler finds conversations that need immediate iteration and assigns them to live idle workers.

The scheduler can run as a thread in the backend process or as an independent process. For stateless deployment, an independent process or container is easier to operate. Multiple scheduler processes are allowed because row locks prevent duplicate claims.

The scheduler has one strict failure rule: if a `RUNNING` lease expires, the conversation is marked `FAILED`. Expiry means worker ownership broke. It is not a normal retry signal.

### Scheduler Run Loop

The scheduler uses poll plus listen. It polls because the conversation row is the source of truth. It listens to `conversation_task_ready` so new work can be found quickly.

Polling also catches retry time and lease expiration, because no notify is sent exactly when a timestamp becomes old enough.

Notification reads must be bounded. In psycopg, an open-ended notification generator can keep waiting after the currently available notifications are consumed. The scheduler should consume currently available input and drain only ready notifications, then return to polling.

```python
while True:
    assign_conversation_pending_loop()
    listen_or_timeout("conversation_task_ready", pollInterval)
```

A scheduler that reconnects to the listen connection must poll before waiting again.

Core function shape:

```python
def assign_conversation_pending_loop():
    while True:
        isAssigned = claim_worker_and_conversation()
        if not isAssigned:
            return
```

### Finding A Conversation And Worker

`claim_worker_and_conversation()` runs in one transaction. It claims one conversation and one idle worker together. A conversation is not leased when no worker is available.

1. Select one conversation needing immediate iteration with `for update skip locked`.
2. If no conversation exists, commit nothing and return false.
3. Select one idle worker with `for update skip locked`.
4. If no worker exists, commit nothing and return false.
5. Generate `leaseId`.
6. Update conversation:
   - `execStatusCode = RUNNING`
   - `leaseId`
   - `leaseWorkerId = workerId`
   - `leaseExpireAt = now() + leaseDuration`
7. Update worker:
   - `conversationId`
   - `leaseId`
   - `assignAt = now()`
   - `updateAt = now()`
8. Keep `stateCode` and `version` unchanged.
9. Notify `conversation_worker_assign`.
10. Commit.

Expired running work is not assigned to another worker. It is failed with `EndAbnormal / BackendException`, `stateCode = FAILED`, `execStatusCode = IDLE`, and cleared lease fields.

### Worker Exit And Timeout

The scheduler usually does nothing when a worker finishes normally. The worker commits the result, clears lease fields, and clears its worker assignment.

The scheduler usually does nothing when a worker handles its own failure. The worker either schedules retry wait or marks the conversation failed, then clears its worker assignment.

The scheduler acts when database state shows stale ownership:

- If `execStatusCode = RUNNING` and `leaseExpireAt <= now()`, the conversation is failed.
- If a worker row points to a lease that no longer exists on the conversation, the scheduler can clear that worker row.
- If a worker heartbeat is older than `workerTimeout`, the scheduler can delete idle stale worker rows. If the worker also owns an expired lease, the conversation is failed.

An expired worker attempt may still finish later. Its final commit cannot pass the lease check because the conversation has already failed and the lease has been cleared.

## Worker

A worker owns one iteration attempt.

The worker can run as a thread or an independent process. For stateless deployment, an independent process or container is the natural form. A process-based worker should register process tracing fields so an operator can identify where it runs.

### Worker Table

`conversation_iter_worker` stores worker liveness and assignment.

| Column | Type | Use |
| --- | --- | --- |
| `workerId` | text primary key | Stable worker identity. |
| `conversationId` | bigint null | Current assigned conversation. |
| `leaseId` | text null | Lease assigned to this worker. |
| `assignAt` | timestamptz | Assignment time. |
| `heartbeatAt` | timestamptz | Worker heartbeat time. |
| `updateAt` | timestamptz | Row update time. |
| `workerProcessId` | integer null | OS process id for tracing when available. |
| `workerHostText` | text null | Host or container name for tracing. |
| `workerStartAt` | timestamptz null | Worker process start time. |

The worker table is dispatch state. The worker still reads `conversation` and verifies the lease before doing work.

An idle worker has:

```text
conversationId = null
leaseId = null
heartbeatAt > now() - workerTimeout
```

Useful index:

```sql
create index conversation_iter_worker_idle_idx
  on conversation_iter_worker(heartbeatAt, workerId)
  where conversationId is null;
```

### Worker Idle Loop

A worker starts by registering or refreshing its `conversation_iter_worker` row, then waits for assignment.

The worker uses poll plus listen. It polls its own worker row because that row is durable dispatch state. It listens to `conversation_worker_assign` so assignment can start quickly.

Like the scheduler, the worker must drain notifications with a bounded read and then continue polling. Notify handling must never become the long-running operation.

```python
while True:
    heartbeat_worker(workerId)
    task = read_worker_task(workerId)
    if task:
        run_worker_task(task)
        continue
    listen_or_timeout("conversation_worker_assign", pollInterval)
```

The notify may wake every worker. Each worker still reads only its own assignment.

`read_worker_task(workerId)` reads the worker row and verifies the conversation lease before returning work:

- worker row has `conversationId` and `leaseId`.
- conversation row has the same `conversationId`.
- conversation row has the same `leaseId`.
- conversation row has `leaseWorkerId = workerId`.
- `leaseExpireAt > now()`.

If the worker row is assigned but the conversation lease does not match, the worker clears its own assignment and returns to idle.

### Normal Worker Run

Core function shape:

```python
def run_worker_task(task):
    data = load_iteration_data(task)
    result = run_iteration(data)
    commit_iteration_result(task, data, result)
```

`load_iteration_data()` verifies lease ownership and records the loaded `version`.

`run_iteration()` does not write parent conversation rows while model or tool calls are running. It builds context from database data and returns a result object:

```python
{
    "eventListNew": [],
    "metadataUpdate": {},
    "stateCodeNext": 100,
    "execStatusCodeNext": None,
}
```

`execStatusCodeNext` is optional. When it is null, commit logic derives it from `stateCodeNext`.

Design target: child conversations should have their own explicit work ownership. In the current implementation, the parent backend tool still runs child subagents inside the parent iteration.

Long iterations refresh the lease before it expires. Lease refresh runs in a short transaction:

1. Lock conversation row.
2. Verify same `leaseId`, `leaseWorkerId`, and `version`.
3. Set `leaseExpireAt = now() + leaseDuration`.
4. Update worker `heartbeatAt`.
5. Commit.

If refresh fails, the worker stops the attempt if it can. If it cannot stop an external call, the final commit still fails because the lease or version no longer matches.

### Normal Commit

`commit_iteration_result()` runs in one transaction:

1. Lock conversation row.
2. Verify:
   - `version` still matches data read before work.
   - `leaseId` matches.
   - `leaseWorkerId` matches.
   - `leaseExpireAt > now()`.
3. Insert new events.
4. Append event ids to `metadata.eventList`.
5. Apply metadata update.
6. Set `stateCode = stateCodeNext`.
7. Increment `version`.
8. Reset retry columns.
9. Clear lease fields.
10. Set `execStatusCode`:
   - result value when `execStatusCodeNext` is provided
   - `PENDING` when `stateCodeNext < 0`
   - `IDLE` when `stateCodeNext > 0`
11. Clear worker assignment.
12. If `stateCodeNext < 0`, notify `conversation_task_ready`.
13. Commit.

If any verification fails, rollback. The attempt has no effect.

External side effects need a separate idempotency rule. Database lease checks prevent duplicate event commits, but they cannot undo a tool call that already happened outside the database.

### Worker Error

If `run_iteration()` raises before commit, the worker handles the failure in one transaction.

Retry logic:

1. Lock conversation row.
2. Verify same `leaseId`, `leaseWorkerId`, and loaded `version`.
3. Increment `leaseRetryCount`.
4. If retry count is below the limit:
   - keep `stateCode` unchanged
   - set `execStatusCode = RETRY_WAIT`
   - set `leaseRetryAfterAt = now() + retryDelay`
   - store the error text in metadata for UI/debugging
   - clear lease fields
   - clear worker assignment
   - notify `conversation_task_ready`
5. If retry count reached the limit:
   - append `EndAbnormal / BackendException` with the actual error text
   - set `metadata.statusText = failed`
   - set `metadata.isUserTurn = false`
   - set `metadata.endStatusText = abnormal`
   - set `stateCode = FAILED`
   - set `execStatusCode = IDLE`
   - increment `version`
   - clear lease fields
   - clear worker assignment

### Worker Crash

If the worker process dies, no release happens. The scheduler later sees expired lease and marks the conversation failed.

The worker heartbeat and tracing columns help distinguish slow work from dead work, but lease expiration is a runtime failure signal.

Startup recovery should release local worker rows whose process is gone or whose heartbeat has timed out. A live process id is not enough to prove worker loops are healthy.

## State Transitions

User input creates a row that needs immediate iteration. The HTTP request commits the user event quickly, then wakes scheduler through notify. Polling still finds the row if notify is missed.

```text
WAIT_USER -> USER_MESSAGE_READY
execStatusCode = PENDING
version += 1
leaseRetryCount = 0
leaseRetryAfterAt = null
notify conversation_task_ready
```

Scheduler claim does not change conversation meaning.

```text
execStatusCode = RUNNING
leaseId = generated id
leaseWorkerId = assigned worker
leaseExpireAt = now() + leaseDuration
version unchanged
notify conversation_worker_assign
```

Agent text reply with no follow-up automation:

```text
USER_MESSAGE_READY -> WAIT_USER
version += 1
execStatusCode = IDLE
lease fields cleared
worker assignment cleared
```

Agent tool call, tool result ready:

```text
USER_MESSAGE_READY -> TOOL_RESULT_READY
version += 1
execStatusCode = PENDING
notify conversation_task_ready
```

Subagent launch requested:

```text
USER_MESSAGE_READY -> SUBAGENT_LAUNCH_READY
version += 1
execStatusCode = PENDING
notify conversation_task_ready
```

Subagent children initialized:

```text
SUBAGENT_LAUNCH_READY -> WAIT_SUBAGENT
version += 1
execStatusCode = IDLE
child conversations use TEMPLATE_START_READY / PENDING
notify conversation_task_ready
```

Subagent results ready:

```text
WAIT_SUBAGENT -> TOOL_RESULT_READY
version += 1
execStatusCode = PENDING
notify conversation_task_ready
```

Conversation ended:

```text
USER_MESSAGE_READY -> COMPLETED
version += 1
execStatusCode = IDLE
```

Worker error with retry:

```text
stateCode unchanged
execStatusCode = RETRY_WAIT
leaseRetryCount += 1
leaseRetryAfterAt = now() + retryDelay
lease fields cleared
worker assignment cleared
notify conversation_task_ready
```

Worker error after retry limit, worker death, or lease expiry:

```text
append EndAbnormal / BackendException
stateCode = FAILED
execStatusCode = IDLE
version += 1
lease fields cleared
worker assignment cleared
```

## Config

Readable names live under `config`. Database stores integer codes.

Readable names are defined by:

- `config/conversation_state.py`
- `config/conversation_exec_status.py`

API responses may include readable text derived from those modules, but writes use codes internally.

## Database Signals

PostgreSQL notify channels are wake-up hints.

| Channel | Listener | Meaning |
| --- | --- | --- |
| `conversation_update` | WebSocket relay | Conversation or event changed. |
| `conversation_task_ready` | Scheduler | Some conversation row may need scheduling. |
| `conversation_worker_assign` | Workers | Worker assignment may have changed. |

Every listener also polls. Notify is not a queue.

## Frontend Update Design

Backend relays database updates to frontend through WebSocket.

Frontend rule:

- WebSocket says refresh soon.
- API response is source of truth.

Frontend also does active refresh because WebSocket or notify can miss updates.

Frontend behavior:

- On `conversation_update`, quietly refresh conversation list.
- If selected conversation matches, refresh events.
- If selected parent has child conversations, refresh visible child state lazily.
- While selected conversation has a running or pending code, run periodic quiet refresh.

The pending message UI can show processing details from the conversation row:

- `execStatusCode` shows pending, running, or retry wait.
- `leaseRetryCount` shows retry number.
- `leaseWorkerId` shows the assigned worker while running.
- `leaseExpireAt` shows the lease deadline while running.
- `leaseRetryAfterAt` shows when retry wait can be scheduled again.

## Invariants

- `conversation` is source of truth.
- Notify is not a queue; polling must be enough to recover.
- Notify reads must be bounded so scheduler and worker loops cannot block while draining notifications.
- Worker assignment table does not authorize writes.
- Lease fields authorize writes.
- Scheduler claims a conversation and worker in one transaction.
- A conversation is not leased when no worker is available.
- `version` increments on semantic commits, not on lease-only commits.
- `stateCode < 0` means scheduler-visible work.
- `stateCode > 0` means no immediate scheduler work.
- Lease expiry is abnormal and fails the conversation.
- A stale worker attempt cannot commit after lease or version mismatch.
- Frontend state is refreshed from API, not trusted from WebSocket data.
