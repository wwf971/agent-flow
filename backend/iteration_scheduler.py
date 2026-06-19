from __future__ import annotations
# pyright: reportMissingImports=false

import json
import os
import select
import socket
import time
import uuid
from contextlib import closing
from threading import Event, Lock, Thread
from typing import Any

from psycopg import connect

from config import CONFIG_DIR
from conversation import get_conversation_by_id, normalize_metadata
from db import dict_cursor, get_runtime_db_config, run_in_transaction
from event import create_event_in_db, list_events_by_conversation

if str(CONFIG_DIR) not in os.sys.path:
    os.sys.path.insert(0, str(CONFIG_DIR))

from conversation_exec_status import EXEC_STATUS_IDLE, EXEC_STATUS_PENDING, EXEC_STATUS_RETRY_WAIT, EXEC_STATUS_RUNNING
from conversation_state import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_SUBAGENT_LAUNCH_READY,
    STATE_TEMPLATE_START_READY,
    STATE_TOOL_RESULT_READY,
    STATE_USER_MESSAGE_READY,
    STATE_WAIT_USER,
)
from subagent_runtime import (
    commit_subagent_child_finish,
    create_subagent_run,
    ensure_subagent_schema_with_cursor,
    initialize_subagent_run,
    prepare_subagent_request_result,
    build_subagent_child_finish_result,
    commit_subagent_child_failed,
)

CHANNEL_TASK_READY = "conversation_task_ready"
CHANNEL_WORKER_ASSIGN = "conversation_worker_assign"

LEASE_SECONDS = int(os.environ.get("CONVERSATION_ITER_LEASE_SECONDS") or "30")
POLL_SECONDS = float(os.environ.get("CONVERSATION_ITER_POLL_SECONDS") or "1")
RETRY_SECONDS = int(os.environ.get("CONVERSATION_ITER_RETRY_SECONDS") or "3")
RETRY_COUNT_MAX = int(os.environ.get("CONVERSATION_ITER_RETRY_COUNT_MAX") or "2")
WORKER_COUNT = int(os.environ.get("CONVERSATION_ITER_WORKER_COUNT") or "2")
WORKER_TIMEOUT_SECONDS = int(os.environ.get("CONVERSATION_ITER_WORKER_TIMEOUT_SECONDS") or "45")
ATTEMPT_SECONDS_MAX = int(os.environ.get("CONVERSATION_ITER_ATTEMPT_SECONDS_MAX") or "120")

runtime_lock = Lock()
is_runtime_started = False


def ensure_conversation_iter_schema():
    def action(db):
        with closing(db.cursor()) as cursor:
            cursor.execute("alter table conversation add column if not exists version bigint not null default 0")
            cursor.execute("alter table conversation add column if not exists stateCode integer not null default 100")
            cursor.execute("alter table conversation add column if not exists execStatusCode integer not null default 0")
            cursor.execute("alter table conversation add column if not exists leaseId text")
            cursor.execute("alter table conversation add column if not exists leaseWorkerId text")
            cursor.execute("alter table conversation add column if not exists leaseExpireAt timestamptz")
            cursor.execute("alter table conversation add column if not exists leaseRetryCount integer not null default 0")
            cursor.execute("alter table conversation add column if not exists leaseRetryAfterAt timestamptz")
            cursor.execute(
                """
                create index if not exists conversation_iter_pending_idx
                on conversation(stateCode, execStatusCode, leaseExpireAt, leaseRetryAfterAt, id)
                where stateCode < 0
                """
            )
            cursor.execute(
                """
                create index if not exists conversation_lease_expire_idx
                on conversation(leaseExpireAt, id)
                where leaseId is not null
                """
            )
            cursor.execute(
                """
                create table if not exists conversation_iter_worker (
                  workerId text primary key,
                  conversationId bigint,
                  leaseId text,
                  assignAt timestamptz,
                  heartbeatAt timestamptz,
                  updateAt timestamptz default now(),
                  workerProcessId integer,
                  workerHostText text,
                  workerStartAt timestamptz
                )
                """
            )
            cursor.execute("alter table conversation_iter_worker add column if not exists workerProcessId integer")
            cursor.execute("alter table conversation_iter_worker add column if not exists workerHostText text")
            cursor.execute("alter table conversation_iter_worker add column if not exists workerStartAt timestamptz")
            cursor.execute(
                """
                create index if not exists conversation_iter_worker_idle_idx
                on conversation_iter_worker(heartbeatAt, workerId)
                where conversationId is null
                """
            )
            ensure_subagent_schema_with_cursor(cursor)
        return {"isConversationIterSchemaReady": True}

    return run_in_transaction(action)


def start_conversation_iter_runtime():
    global is_runtime_started
    with runtime_lock:
        if is_runtime_started:
            return {"isStarted": False}
        recover_conversation_iter_startup()
        is_runtime_started = True
        worker_id_list = []
        for worker_index in range(max(1, WORKER_COUNT)):
            worker_id = _build_worker_id(worker_index)
            _register_worker(worker_id)
            worker_id_list.append(worker_id)
        _assign_conversation_pending_loop()
        for worker_id in worker_id_list:
            Thread(target=_run_worker_loop_safe, args=(worker_id,), daemon=True).start()
        Thread(target=_run_scheduler_loop_safe, daemon=True).start()
        return {"isStarted": True, "workerCount": max(1, WORKER_COUNT)}


def recover_conversation_iter_startup():
    def action(db):
        worker_id_list = _get_worker_id_list_dead_local(db)
        if not worker_id_list:
            return {"workerDeadCount": 0, "conversationReleasedCount": 0}
        conversation_failed_count = 0
        with closing(dict_cursor(db)) as cursor:
            cursor.execute(
                """
                select id, leaseWorkerId
                from conversation
                where stateCode < 0
                  and leaseWorkerId = any(%s)
                for update
                """,
                (worker_id_list,),
            )
            row_list = cursor.fetchall() or []
            for row in row_list:
                _fail_conversation_iteration(
                    db,
                    int(row["id"]),
                    str(row.get("leaseworkerid") or ""),
                    "conversation worker stopped before finishing iteration",
                    0,
                )
                conversation_failed_count += 1
            cursor.execute("delete from conversation_iter_worker where workerId = any(%s)", (worker_id_list,))
        return {
            "workerDeadCount": len(worker_id_list),
            "conversationFailedCount": conversation_failed_count,
        }

    return run_in_transaction(action)


def _get_worker_id_list_dead_local(db):
    host_text = socket.gethostname()
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            """
            select
                workerId,
                workerProcessId,
                heartbeatAt <= now() - (%s || ' seconds')::interval as isHeartbeatTimeout,
                conversationId
            from conversation_iter_worker
            where workerHostText = %s
            """,
            (WORKER_TIMEOUT_SECONDS, host_text),
        )
        row_list = cursor.fetchall() or []
    worker_id_list = []
    for row in row_list:
        process_id = int(row.get("workerprocessid") or 0)
        if not _is_process_alive(process_id):
            worker_id_list.append(str(row["workerid"]))
            continue
        if row.get("isheartbeattimeout") is True:
            worker_id_list.append(str(row["workerid"]))
    return worker_id_list


def _is_process_alive(process_id: int):
    if process_id < 1:
        return False
    try:
        os.kill(process_id, 0)
        return True
    except OSError:
        return False


def mark_conversation_user_message_ready(db, conversation_id: int, timezone: int):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute("select metadata from conversation where id = %s for update", (conversation_id,))
        row = cursor.fetchone()
        if not row:
            raise RuntimeError("conversation not found")
        metadata_next = normalize_metadata(row["metadata"])
        metadata_next["isUserTurn"] = False
        cursor.execute(
            """
            update conversation
            set metadata = %s::jsonb,
                stateCode = %s,
                execStatusCode = %s,
                version = version + 1,
                leaseId = null,
                leaseWorkerId = null,
                leaseExpireAt = null,
                leaseRetryCount = 0,
                leaseRetryAfterAt = null,
                updateAt = now(),
                updateAtTimezone = %s
            where id = %s
            """,
            (
                json.dumps(metadata_next),
                STATE_USER_MESSAGE_READY,
                EXEC_STATUS_PENDING,
                timezone,
                conversation_id,
            ),
        )
        cursor.execute("select pg_notify(%s, '')", (CHANNEL_TASK_READY,))
    return metadata_next


def _build_worker_id(worker_index: int):
    return f"{socket.gethostname()}-{os.getpid()}-{worker_index}-{uuid.uuid4().hex[:8]}"


def _run_scheduler_loop_safe():
    while True:
        try:
            _run_scheduler_loop()
        except Exception:
            time.sleep(POLL_SECONDS)


def _run_scheduler_loop():
    with connect(**get_runtime_db_config(), autocommit=True) as db:
        with db.cursor() as cursor:
            cursor.execute(f"listen {CHANNEL_TASK_READY}")
        while True:
            _assign_conversation_pending_loop()
            readable, _writable, _error = select.select([db], [], [], POLL_SECONDS)
            if readable:
                _drain_ready_notifications(db)


def _drain_ready_notifications(db):
    # `Connection.notifies()` is an endless generator in this psycopg version.
    # Drain only ready notifications, then return to polling the database.
    db.pgconn.consume_input()
    while db.pgconn.notifies() is not None:
        pass


def _assign_conversation_pending_loop():
    while True:
        is_assigned = run_in_transaction(_claim_worker_and_conversation)
        if not is_assigned:
            return


def _claim_worker_and_conversation(db):
    _clear_worker_stale(db)
    # Lease expiry is not retryable work. It means the worker failed to keep
    # ownership alive, so the conversation is failed with a clear reason.
    if _fail_next_expired_running_conversation(db):
        return True
    conversation = _select_conversation_ready(db)
    if not conversation:
        return False
    worker = _select_worker_idle(db)
    if not worker:
        return False
    lease_id = uuid.uuid4().hex
    worker_id = str(worker["workerid"])
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            """
            update conversation
            set execStatusCode = %s,
                leaseId = %s,
                leaseWorkerId = %s,
                leaseExpireAt = now() + (%s || ' seconds')::interval,
                updateAt = now()
            where id = %s
            """,
            (
                EXEC_STATUS_RUNNING,
                lease_id,
                worker_id,
                LEASE_SECONDS,
                int(conversation["id"]),
            ),
        )
        cursor.execute(
            """
            update conversation_iter_worker
            set conversationId = %s,
                leaseId = %s,
                assignAt = now(),
                updateAt = now()
            where workerId = %s
            """,
            (int(conversation["id"]), lease_id, worker_id),
        )
        cursor.execute("select pg_notify(%s, '')", (CHANNEL_WORKER_ASSIGN,))
    return True


def _select_conversation_ready(db):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            """
            select id
            from conversation
            where stateCode < 0
              and execStatusCode in (%s, %s, %s)
              and leaseId is null
              and (leaseRetryAfterAt is null or leaseRetryAfterAt <= now())
            order by updateAt asc, id asc
            limit 1
            for update skip locked
            """,
            (EXEC_STATUS_IDLE, EXEC_STATUS_PENDING, EXEC_STATUS_RETRY_WAIT),
        )
        return cursor.fetchone()


def _select_worker_idle(db):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            """
            select workerId
            from conversation_iter_worker
            where conversationId is null
              and heartbeatAt > now() - (%s || ' seconds')::interval
            order by heartbeatAt asc, workerId asc
            limit 1
            for update skip locked
            """,
            (WORKER_TIMEOUT_SECONDS,),
        )
        return cursor.fetchone()


def _fail_next_expired_running_conversation(db):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            """
            select id, leaseWorkerId, updateAtTimezone
            from conversation
            where stateCode < 0
              and execStatusCode = %s
              and leaseId is not null
              and leaseExpireAt <= now()
            order by leaseExpireAt asc, id asc
            limit 1
            for update skip locked
            """,
            (EXEC_STATUS_RUNNING,),
        )
        row = cursor.fetchone()
    if not row:
        return False
    _fail_conversation_iteration(
        db,
        int(row["id"]),
        str(row.get("leaseworkerid") or ""),
        "conversation iteration lease expired before worker finished",
        int(row.get("updateattimezone") or 0),
    )
    return True


def _clear_worker_stale(db):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            """
            select conversation.id, worker.workerId, conversation.updateAtTimezone
            from conversation_iter_worker worker
            join conversation on conversation.id = worker.conversationId
            where worker.heartbeatAt <= now() - (%s || ' seconds')::interval
              and conversation.stateCode < 0
              and conversation.execStatusCode = %s
              and conversation.leaseExpireAt <= now()
            for update of conversation skip locked
            """,
            (WORKER_TIMEOUT_SECONDS, EXEC_STATUS_RUNNING),
        )
        row_list = cursor.fetchall() or []
        for row in row_list:
            _fail_conversation_iteration(
                db,
                int(row["id"]),
                str(row.get("workerid") or ""),
                "conversation worker heartbeat stopped and lease expired",
                int(row.get("updateattimezone") or 0),
            )
        cursor.execute(
            """
            delete from conversation_iter_worker
            where heartbeatAt <= now() - (%s || ' seconds')::interval
              and conversationId is null
            """,
            (WORKER_TIMEOUT_SECONDS,),
        )
        cursor.execute(
            """
            update conversation_iter_worker worker
            set conversationId = null,
                leaseId = null,
                updateAt = now()
            where conversationId is not null
              and not exists (
                select 1
                from conversation
                where id = worker.conversationId
                  and leaseId = worker.leaseId
                  and leaseWorkerId = worker.workerId
              )
            """
        )


def _fail_conversation_iteration(db, conversation_id: int, worker_id: str, error_text: str, timezone: int):
    _create_iteration_error_event(db, conversation_id, error_text, timezone)
    metadata_next = _get_metadata_failed(db, conversation_id, error_text)
    with closing(db.cursor()) as cursor:
        cursor.execute(
            """
            update conversation
            set metadata = %s::jsonb,
                stateCode = %s,
                execStatusCode = %s,
                leaseId = null,
                leaseWorkerId = null,
                leaseExpireAt = null,
                leaseRetryAfterAt = null,
                version = version + 1,
                updateAt = now(),
                updateAtTimezone = %s
            where id = %s
            """,
            (json.dumps(metadata_next), STATE_FAILED, EXEC_STATUS_IDLE, timezone, conversation_id),
        )
        if worker_id:
            _clear_worker_assignment_with_cursor(cursor, worker_id)
        else:
            cursor.execute(
                """
                update conversation_iter_worker
                set conversationId = null,
                    leaseId = null,
                    updateAt = now()
                where conversationId = %s
                """,
                (conversation_id,),
            )
    commit_subagent_child_failed(db, conversation_id, timezone, error_text)
    return True


def _get_metadata_failed(db, conversation_id: int, error_text: str = ""):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute("select metadata from conversation where id = %s for update", (conversation_id,))
        row = cursor.fetchone()
    metadata_next = normalize_metadata(row["metadata"] if row else {})
    metadata_next["statusText"] = "failed"
    metadata_next["isUserTurn"] = False
    metadata_next["endStatusText"] = "abnormal"
    if error_text:
        metadata_next["endReasonText"] = error_text
    return metadata_next


def _run_worker_loop_safe(worker_id: str):
    while True:
        try:
            _register_worker(worker_id)
            _run_worker_loop(worker_id)
        except Exception:
            time.sleep(POLL_SECONDS)


def _run_worker_loop(worker_id: str):
    with connect(**get_runtime_db_config(), autocommit=True) as db:
        with db.cursor() as cursor:
            cursor.execute(f"listen {CHANNEL_WORKER_ASSIGN}")
        while True:
            _heartbeat_worker(worker_id)
            task = run_in_transaction(lambda db_item: _read_worker_task(db_item, worker_id))
            if task:
                _run_worker_task(task)
                continue
            readable, _writable, _error = select.select([db], [], [], POLL_SECONDS)
            if readable:
                _drain_ready_notifications(db)


def _register_worker(worker_id: str):
    run_in_transaction(lambda db: _register_worker_in_db(db, worker_id))


def _register_worker_in_db(db, worker_id: str):
    with closing(db.cursor()) as cursor:
        cursor.execute(
            """
            insert into conversation_iter_worker(
                workerId,
                conversationId,
                leaseId,
                heartbeatAt,
                updateAt,
                workerProcessId,
                workerHostText,
                workerStartAt
            )
            values (%s, null, null, now(), now(), %s, %s, now())
            on conflict (workerId) do update
            set conversationId = null,
                leaseId = null,
                heartbeatAt = now(),
                updateAt = now(),
                workerProcessId = excluded.workerProcessId,
                workerHostText = excluded.workerHostText,
                workerStartAt = excluded.workerStartAt
            """,
            (worker_id, os.getpid(), socket.gethostname()),
        )


def _heartbeat_worker(worker_id: str):
    def action(db):
        with closing(db.cursor()) as cursor:
            cursor.execute(
                """
                update conversation_iter_worker
                set heartbeatAt = now(),
                    updateAt = now()
                where workerId = %s
                """,
                (worker_id,),
            )
            if cursor.rowcount < 1:
                _register_worker_in_db(db, worker_id)
        return True

    return run_in_transaction(action)


def _read_worker_task(db, worker_id: str):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            """
            select workerId, conversationId, leaseId
            from conversation_iter_worker
            where workerId = %s
            for update
            """,
            (worker_id,),
        )
        worker = cursor.fetchone()
        if not worker or not worker.get("conversationid") or not worker.get("leaseid"):
            return None
        cursor.execute(
            """
            select id, metadata, version, stateCode, execStatusCode, leaseId, leaseWorkerId,
                   leaseExpireAt, updateAtTimezone
            from conversation
            where id = %s
            for update
            """,
            (int(worker["conversationid"]),),
        )
        conversation = cursor.fetchone()
        is_lease_match = (
            conversation
            and str(conversation.get("leaseid") or "") == str(worker.get("leaseid") or "")
            and str(conversation.get("leaseworkerid") or "") == worker_id
            and conversation.get("leaseexpireat") is not None
        )
        if not is_lease_match:
            _clear_worker_assignment_with_cursor(cursor, worker_id)
            return None
        cursor.execute("select now() as nowValue")
        now_row = cursor.fetchone()
        if conversation["leaseexpireat"] <= now_row["nowvalue"]:
            _fail_conversation_iteration(
                db,
                int(conversation["id"]),
                worker_id,
                "conversation iteration lease expired before worker started",
                int(conversation.get("updateattimezone") or 0),
            )
            return None
        return {
            "workerId": worker_id,
            "conversationId": int(conversation["id"]),
            "leaseId": str(conversation["leaseid"]),
            "version": int(conversation["version"]),
            "stateCode": int(conversation["statecode"]),
            "timezone": int(conversation.get("updateattimezone") or 0),
            "metadata": normalize_metadata(conversation["metadata"]),
        }


def _clear_worker_assignment_with_cursor(cursor, worker_id: str):
    cursor.execute(
        """
        update conversation_iter_worker
        set conversationId = null,
            leaseId = null,
            updateAt = now()
        where workerId = %s
        """,
        (worker_id,),
    )


def _run_worker_task(task: dict[str, Any]):
    try:
        data = _load_iteration_data(task)
        if not data:
            return
        event_stop = Event()
        Thread(target=_refresh_lease_loop, args=(task, int(data["version"]), event_stop), daemon=True).start()
        try:
            result = _run_iteration(data)
        finally:
            event_stop.set()
        run_in_transaction(lambda db: _commit_iteration_result(db, task, data, result))
    except Exception as error:
        try:
            run_in_transaction(lambda db: _release_iteration_error(db, task, error))
        except Exception:
            pass


def _refresh_lease_loop(task: dict[str, Any], version: int, event_stop: Event):
    wait_seconds = max(5, min(30, LEASE_SECONDS // 3))
    time_start = time.monotonic()
    while not event_stop.wait(wait_seconds):
        if time.monotonic() - time_start > ATTEMPT_SECONDS_MAX:
            return
        try:
            is_refreshed = run_in_transaction(lambda db: _refresh_lease(db, task, version))
            if not is_refreshed:
                return
        except Exception:
            return


def _refresh_lease(db, task: dict[str, Any], version: int):
    with closing(db.cursor()) as cursor:
        cursor.execute(
            """
            update conversation
            set leaseExpireAt = now() + (%s || ' seconds')::interval,
                updateAt = now()
            where id = %s
              and version = %s
              and leaseId = %s
              and leaseWorkerId = %s
              and leaseExpireAt > now()
            """,
            (LEASE_SECONDS, int(task["conversationId"]), version, str(task["leaseId"]), str(task["workerId"])),
        )
        if cursor.rowcount < 1:
            return False
        cursor.execute(
            """
            update conversation_iter_worker
            set heartbeatAt = now(),
                updateAt = now()
            where workerId = %s
              and conversationId = %s
              and leaseId = %s
            """,
            (str(task["workerId"]), int(task["conversationId"]), str(task["leaseId"])),
        )
    return True


def _load_iteration_data(task: dict[str, Any]):
    def action(db):
        task_next = _read_worker_task(db, str(task["workerId"]))
        if not task_next:
            return None
        event_list = list_events_by_conversation(db, int(task_next["conversationId"]))
        conversation = get_conversation_by_id(db, int(task_next["conversationId"]))
        metadata = normalize_metadata(conversation["metadata"])
        message_text = ""
        for event_item in reversed(event_list):
            if event_item.get("typeText") == "userMessage" and event_item.get("subtypeText") == "textSimple":
                message_text = str(event_item.get("contentText") or "")
                break
        return {
            **task_next,
            "eventList": event_list,
            "messageText": message_text,
            "templateKey": str(metadata.get("templateKey") or "free-talk"),
        }

    return run_in_transaction(action)


def _run_iteration(data: dict[str, Any]):
    from iteration_executor import _get_turn_finish_metadata, run_orchestrator

    state_code = int(data["stateCode"])
    if state_code == STATE_SUBAGENT_LAUNCH_READY:
        return {
            "eventListNew": [],
            "metadataUpdate": {},
            "stateCodeNext": STATE_SUBAGENT_LAUNCH_READY,
            "execStatusCodeNext": EXEC_STATUS_RUNNING,
            "subAgentLaunch": True,
        }
    if state_code == STATE_TEMPLATE_START_READY:
        event_list_new = list(
            run_orchestrator(
                {
                    "iterType": "templateStart",
                    "templateKey": data["templateKey"],
                    "conversationId": str(data["conversationId"]),
                    "initialPrompt": str(data["metadata"].get("subAgentInitialPrompt") or ""),
                    "maxTurns": int(data["metadata"].get("subAgentMaxTurns") or 0),
                    "eventList": data["eventList"],
                    "logDir": None,
                    "timezone": data["timezone"],
                }
            )
        )
        child_finish_result = build_subagent_child_finish_result(data, event_list_new)
        return {
            "eventListNew": event_list_new,
            "metadataUpdate": child_finish_result["metadataUpdate"],
            "stateCodeNext": child_finish_result["stateCodeNext"],
            "execStatusCodeNext": child_finish_result["execStatusCodeNext"],
            "subAgentChildFinish": child_finish_result,
        }
    if state_code == STATE_TOOL_RESULT_READY:
        event_list_new = list(
            run_orchestrator(
                {
                    "iterType": "toolResult",
                    "templateKey": data["templateKey"],
                    "conversationId": str(data["conversationId"]),
                    "messageText": "",
                    "eventList": data["eventList"],
                    "logDir": None,
                    "timezone": data["timezone"],
                }
            )
        )
        metadata_update = _get_turn_finish_metadata(event_list_new)
        state_next = STATE_COMPLETED if metadata_update.get("statusText") == "completed" else STATE_WAIT_USER
        subagent_request = prepare_subagent_request_result(event_list_new)
        if subagent_request:
            metadata_update = {"isUserTurn": False}
            state_next = STATE_SUBAGENT_LAUNCH_READY
        return {
            "eventListNew": event_list_new,
            "metadataUpdate": metadata_update,
            "stateCodeNext": state_next,
            "execStatusCodeNext": None,
            "subAgentRequest": subagent_request,
        }
    if state_code == STATE_USER_MESSAGE_READY:
        event_list_new = list(
            run_orchestrator(
                {
                    "iterType": "userMessage",
                    "templateKey": data["templateKey"],
                    "conversationId": str(data["conversationId"]),
                    "messageText": data["messageText"],
                    "eventList": data["eventList"],
                    "logDir": None,
                    "timezone": data["timezone"],
                }
            )
        )
        metadata_update = _get_turn_finish_metadata(event_list_new)
        state_next = STATE_COMPLETED if metadata_update.get("statusText") == "completed" else STATE_WAIT_USER
        subagent_request = prepare_subagent_request_result(event_list_new)
        if subagent_request:
            metadata_update = {"isUserTurn": False}
            state_next = STATE_SUBAGENT_LAUNCH_READY
        return {
            "eventListNew": event_list_new,
            "metadataUpdate": metadata_update,
            "stateCodeNext": state_next,
            "execStatusCodeNext": None,
            "subAgentRequest": subagent_request,
        }
    return {
        "eventListNew": [],
        "metadataUpdate": {"isUserTurn": True},
        "stateCodeNext": STATE_WAIT_USER,
        "execStatusCodeNext": EXEC_STATUS_IDLE,
    }


def _commit_iteration_result(db, task: dict[str, Any], data: dict[str, Any], result: dict[str, Any]):
    _verify_conversation_lease(db, task, data["version"])
    conversation_id = int(task["conversationId"])
    timezone = int(data.get("timezone") or 0)
    if result.get("subAgentLaunch") is True:
        result_launch = initialize_subagent_run(db, conversation_id, timezone)
        with closing(dict_cursor(db)) as cursor:
            cursor.execute("select metadata from conversation where id = %s for update", (conversation_id,))
            row = cursor.fetchone()
            if not row:
                raise RuntimeError("conversation not found")
            metadata_next = normalize_metadata(row["metadata"])
            metadata_next.update(result_launch["metadataUpdate"])
            cursor.execute(
                """
                update conversation
                set metadata = %s::jsonb,
                    stateCode = %s,
                    execStatusCode = %s,
                    version = version + 1,
                    leaseId = null,
                    leaseWorkerId = null,
                    leaseExpireAt = null,
                    leaseRetryCount = 0,
                    leaseRetryAfterAt = null,
                    updateAt = now(),
                    updateAtTimezone = %s
                where id = %s
                """,
                (
                    json.dumps(metadata_next),
                    int(result_launch["stateCodeNext"]),
                    int(result_launch["execStatusCodeNext"]),
                    timezone,
                    conversation_id,
                ),
            )
            _clear_worker_assignment_with_cursor(cursor, str(task["workerId"]))
            cursor.execute("select pg_notify(%s, '')", (CHANNEL_TASK_READY,))
        return
    event_created_list = []
    for event_item in result.get("eventListNew") or []:
        event_created = create_event_in_db(
            db,
            conversation_id,
            event_item.get("typeText") or "agentMessage",
            event_item.get("subtypeText") or "textSimple",
            event_item.get("contentType") or 1,
            event_item.get("contentText"),
            event_item.get("contentJson"),
            event_item.get("metadata"),
            timezone,
        )
        event_created_list.append(event_created)
    subagent_request = result.get("subAgentRequest") if isinstance(result.get("subAgentRequest"), dict) else None
    if subagent_request:
        event_index = int(subagent_request.get("eventIndex") or 0)
        if event_index >= len(event_created_list):
            raise RuntimeError("subagent request event was not committed")
        create_subagent_run(db, conversation_id, event_created_list[event_index], subagent_request)
    metadata_update = result.get("metadataUpdate") if isinstance(result.get("metadataUpdate"), dict) else {}
    state_next = int(result.get("stateCodeNext") or STATE_WAIT_USER)
    exec_status_next = result.get("execStatusCodeNext")
    if exec_status_next is None:
        exec_status_next = EXEC_STATUS_PENDING if state_next < 0 else EXEC_STATUS_IDLE
    with closing(dict_cursor(db)) as cursor:
        cursor.execute("select metadata from conversation where id = %s for update", (conversation_id,))
        row = cursor.fetchone()
        if not row:
            raise RuntimeError("conversation not found")
        metadata_next = normalize_metadata(row["metadata"])
        metadata_next.update(metadata_update)
        cursor.execute(
            """
            update conversation
            set metadata = %s::jsonb,
                stateCode = %s,
                execStatusCode = %s,
                version = version + 1,
                leaseId = null,
                leaseWorkerId = null,
                leaseExpireAt = null,
                leaseRetryCount = 0,
                leaseRetryAfterAt = null,
                updateAt = now(),
                updateAtTimezone = %s
            where id = %s
            """,
            (json.dumps(metadata_next), state_next, int(exec_status_next), timezone, conversation_id),
        )
        _clear_worker_assignment_with_cursor(cursor, str(task["workerId"]))
        if state_next < 0:
            cursor.execute("select pg_notify(%s, '')", (CHANNEL_TASK_READY,))
    subagent_child_finish = result.get("subAgentChildFinish") if isinstance(result.get("subAgentChildFinish"), dict) else None
    if subagent_child_finish:
        commit_subagent_child_finish(db, conversation_id, timezone, subagent_child_finish)


def _verify_conversation_lease(db, task: dict[str, Any], version: int):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            """
            select id
            from conversation
            where id = %s
              and version = %s
              and leaseId = %s
              and leaseWorkerId = %s
              and leaseExpireAt > now()
            for update
            """,
            (int(task["conversationId"]), version, str(task["leaseId"]), str(task["workerId"])),
        )
        if not cursor.fetchone():
            raise RuntimeError("conversation lease is not valid")


def _release_iteration_error(db, task: dict[str, Any], error: Exception):
    conversation_id = int(task["conversationId"])
    worker_id = str(task["workerId"])
    lease_id = str(task["leaseId"])
    error_text = str(error)
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            """
            select id, metadata, leaseRetryCount
            from conversation
            where id = %s
              and leaseId = %s
              and leaseWorkerId = %s
            for update
            """,
            (conversation_id, lease_id, worker_id),
        )
        row = cursor.fetchone()
        if not row:
            _clear_worker_assignment_with_cursor(cursor, worker_id)
            return
        # Retry only real iteration errors caught by the owning worker.
        # Scheduler-side lease expiry is handled elsewhere as a runtime failure.
        retry_count_next = int(row.get("leaseretrycount") or 0) + 1
        if retry_count_next >= RETRY_COUNT_MAX:
            _fail_conversation_iteration(db, conversation_id, worker_id, error_text, int(task.get("timezone") or 0))
            return
        metadata_next = normalize_metadata(row["metadata"])
        metadata_next["iterationErrorText"] = error_text
        cursor.execute(
            """
            update conversation
            set metadata = %s::jsonb,
                execStatusCode = %s,
                leaseId = null,
                leaseWorkerId = null,
                leaseExpireAt = null,
                leaseRetryCount = %s,
                leaseRetryAfterAt = now() + (%s || ' seconds')::interval,
                updateAt = now()
            where id = %s
            """,
            (json.dumps(metadata_next), EXEC_STATUS_RETRY_WAIT, retry_count_next, RETRY_SECONDS, conversation_id),
        )
        _clear_worker_assignment_with_cursor(cursor, worker_id)
        cursor.execute("select pg_notify(%s, '')", (CHANNEL_TASK_READY,))


def _create_iteration_error_event(db, conversation_id: int, error_text: str, timezone: int):
    create_event_in_db(
        db,
        conversation_id,
        "EndAbnormal",
        "BackendException",
        1,
        error_text,
        None,
        {"errorText": error_text},
        timezone,
    )
