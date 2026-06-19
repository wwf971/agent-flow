from __future__ import annotations
# pyright: reportMissingImports=false

import json
import os
import sys
import uuid
from contextlib import closing
from typing import Any

from conifg_template import get_template_by_key
from conversation import create_conversation_in_db, get_conversation_by_id, normalize_metadata
from event import create_event_in_db, list_events_by_conversation

from config import CONFIG_DIR

if str(CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(CONFIG_DIR))

from conversation_exec_status import EXEC_STATUS_IDLE, EXEC_STATUS_PENDING
from conversation_state import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_TEMPLATE_START_READY,
    STATE_TOOL_RESULT_READY,
    STATE_WAIT_SUBAGENT,
)

CHANNEL_TASK_READY = "conversation_task_ready"
TOOL_NAME_SUBAGENT = "tool_subagent"


def ensure_subagent_schema_with_cursor(cursor):
    cursor.execute(
        """
        create table if not exists subagent_run (
          runId text primary key,
          parentConversationId bigint not null references conversation(id) on delete cascade,
          requestEventId bigint not null references event(id) on delete cascade,
          startEventId bigint references event(id) on delete set null,
          resultEventId bigint references event(id) on delete set null,
          statusText text not null,
          childCount integer not null default 0,
          childTerminalCount integer not null default 0,
          childSuccessCount integer not null default 0,
          childFailureCount integer not null default 0,
          requestJson jsonb,
          createAt timestamptz default now(),
          updateAt timestamptz default now()
        )
        """
    )
    cursor.execute(
        """
        create table if not exists subagent_run_child (
          runId text not null references subagent_run(runId) on delete cascade,
          childConversationId bigint not null references conversation(id) on delete cascade,
          parentConversationId bigint not null references conversation(id) on delete cascade,
          childIndex integer not null,
          nameText text not null,
          statusText text not null,
          turnCount integer not null default 0,
          latestToolCallJson jsonb,
          returnJson jsonb,
          failureText text,
          createAt timestamptz default now(),
          updateAt timestamptz default now(),
          primary key (runId, childConversationId)
        )
        """
    )
    cursor.execute(
        """
        create index if not exists subagent_run_parent_idx
        on subagent_run(parentConversationId, updateAt desc, runId)
        """
    )
    cursor.execute(
        """
        create index if not exists subagent_run_child_run_idx
        on subagent_run_child(runId, childIndex, childConversationId)
        """
    )


def get_is_subagent_tool_call_event(event_item: dict[str, Any]):
    if event_item.get("subtypeText") != "toolCall":
        return False
    content_json = event_item.get("contentJson") if isinstance(event_item.get("contentJson"), dict) else {}
    return str(content_json.get("tool_name") or "") == TOOL_NAME_SUBAGENT


def prepare_subagent_request_result(event_list_new: list[dict[str, Any]]):
    for event_index, event_item in enumerate(event_list_new):
        if not get_is_subagent_tool_call_event(event_item):
            continue
        event_next = dict(event_item)
        content_json = dict(event_item.get("contentJson") if isinstance(event_item.get("contentJson"), dict) else {})
        args_data = dict(content_json.get("args") if isinstance(content_json.get("args"), dict) else {})
        item_list, max_turns = normalize_subagent_request(args_data)
        run_id = str(args_data.get("subAgentRunId") or uuid.uuid4().hex)
        args_data["subAgentRunId"] = run_id
        args_data["maxTurns"] = max_turns
        args_data["subagents"] = [
            {
                "name": item["name"],
                "initialPrompt": item["initialPrompt"],
            }
            for item in item_list
        ]
        content_json["args"] = args_data
        event_next["contentJson"] = content_json
        metadata_next = dict(event_item.get("metadata") if isinstance(event_item.get("metadata"), dict) else {})
        metadata_next["toolName"] = TOOL_NAME_SUBAGENT
        metadata_next["subAgentRunId"] = run_id
        event_next["metadata"] = metadata_next
        event_list_new[event_index] = event_next
        return {
            "runId": run_id,
            "eventIndex": event_index,
            "itemList": item_list,
            "maxTurns": max_turns,
            "requestJson": content_json,
        }
    return None


def normalize_subagent_request(args: Any):
    args_data = args if isinstance(args, dict) else {}
    item_list_raw = args_data.get("subagents") if isinstance(args_data.get("subagents"), list) else []
    item_list = []
    for index, item_raw in enumerate(item_list_raw[:4]):
        item = item_raw if isinstance(item_raw, dict) else {}
        initial_prompt = _to_text(item.get("initialPrompt"))
        if not initial_prompt:
            continue
        item_list.append({
            "index": index,
            "name": _to_text(item.get("name")) or f"subagent {index + 1}",
            "initialPrompt": initial_prompt,
        })
    try:
        max_turns = max(1, min(12, int(args_data.get("maxTurns") or 6)))
    except (TypeError, ValueError):
        max_turns = 6
    if not item_list:
        raise RuntimeError("tool_subagent requires at least one subagent with initialPrompt")
    return item_list, max_turns


def create_subagent_run(db, parent_conversation_id: int, event_request: dict[str, Any], request_data: dict[str, Any]):
    with closing(db.cursor()) as cursor:
        cursor.execute(
            """
            insert into subagent_run(
                runId,
                parentConversationId,
                requestEventId,
                statusText,
                childCount,
                requestJson,
                updateAt
            )
            values (%s, %s, %s, %s, %s, %s::jsonb, now())
            on conflict (runId) do nothing
            """,
            (
                request_data["runId"],
                parent_conversation_id,
                int(event_request["id"]),
                "launchReady",
                len(request_data["itemList"]),
                json.dumps(request_data["requestJson"]),
            ),
        )


def initialize_subagent_run(db, parent_conversation_id: int, timezone: int):
    event_request = get_latest_subagent_request_event(db, parent_conversation_id)
    content_json = event_request.get("contentJson") if isinstance(event_request.get("contentJson"), dict) else {}
    args_data = content_json.get("args") if isinstance(content_json.get("args"), dict) else {}
    run_id = str(args_data.get("subAgentRunId") or "")
    if not run_id:
        raise RuntimeError("subAgentRunId is missing")
    item_list, max_turns = normalize_subagent_request(args_data)
    run_row = lock_subagent_run(db, run_id, parent_conversation_id)
    if str(run_row.get("statustext") or "") != "launchReady":
        raise RuntimeError("subagent run is not launch ready")
    child_list = create_subagent_child_list(db, parent_conversation_id, run_id, item_list, max_turns, int(event_request["id"]), timezone)
    event_start = create_event_in_db(
        db,
        parent_conversation_id,
        "orchestratorMessage",
        "subAgentStart",
        3,
        f"Started {len(child_list)} subagent conversation(s).",
        build_subagent_event_content(
            "subAgentStart",
            {
                "statusText": "running",
                "parentConversationId": str(parent_conversation_id),
                "subAgentRunId": run_id,
                "maxTurns": max_turns,
                "childConversationIdList": [child["conversationId"] for child in child_list],
                "subagents": child_list,
            },
        ),
        {
            "templateKey": get_parent_template_key(db, parent_conversation_id),
            "toolName": TOOL_NAME_SUBAGENT,
            "subAgentRunId": run_id,
            "childConversationIdList": [child["conversationId"] for child in child_list],
        },
        timezone,
    )
    update_subagent_run_started(db, run_id, int(event_start["id"]), len(child_list))
    metadata_update = build_parent_subagent_run_metadata(db, parent_conversation_id, run_id, event_start, child_list)
    return {
        "metadataUpdate": metadata_update,
        "stateCodeNext": STATE_WAIT_SUBAGENT,
        "execStatusCodeNext": EXEC_STATUS_IDLE,
    }


def commit_subagent_child_finish(db, child_conversation_id: int, timezone: int, result_child: dict[str, Any]):
    metadata_child = result_child.get("metadataChild") if isinstance(result_child.get("metadataChild"), dict) else {}
    run_id = str(metadata_child.get("subAgentRunId") or "")
    if not run_id:
        return False
    child_result = result_child.get("childResult") if isinstance(result_child.get("childResult"), dict) else {}
    latest_tool_call = result_child.get("latestToolCall") if isinstance(result_child.get("latestToolCall"), dict) else None
    status_text = "completed" if child_result.get("isReturned") is True else "failed"
    with closing(db.cursor()) as cursor:
        cursor.execute(
            """
            update subagent_run_child
            set statusText = %s,
                turnCount = %s,
                latestToolCallJson = %s::jsonb,
                returnJson = %s::jsonb,
                failureText = %s,
                updateAt = now()
            where runId = %s
              and childConversationId = %s
            """,
            (
                status_text,
                int(child_result.get("turnCount") or 0),
                json.dumps(latest_tool_call) if latest_tool_call is not None else None,
                json.dumps(child_result),
                str(child_result.get("failureReason") or ""),
                run_id,
                child_conversation_id,
            ),
        )
        cursor.execute(
            """
            select parentConversationId, resultEventId, statusText
            from subagent_run
            where runId = %s
            for update
            """,
            (run_id,),
        )
        run_row = cursor.fetchone()
    if not run_row or run_row[1] is not None:
        return False
    parent_conversation_id = int(run_row[0])
    summary = get_subagent_run_summary(db, run_id)
    update_subagent_run_counts(db, run_id, summary)
    if summary["childTerminalCount"] < summary["childCount"]:
        return False
    event_result = create_subagent_result_event(db, parent_conversation_id, run_id, summary, timezone)
    wake_parent_for_subagent_result(db, parent_conversation_id, run_id, int(event_result["id"]), summary, timezone)
    return True


def commit_subagent_child_failed(db, child_conversation_id: int, timezone: int, error_text: str):
    conversation = get_conversation_by_id(db, child_conversation_id)
    metadata_child = normalize_metadata(conversation["metadata"])
    run_id = str(metadata_child.get("subAgentRunId") or "")
    if not run_id:
        return False
    event_list = list_events_by_conversation(db, child_conversation_id)
    latest_tool_call = get_latest_tool_call_summary(event_list)
    return commit_subagent_child_finish(
        db,
        child_conversation_id,
        timezone,
        {
            "metadataChild": metadata_child,
            "childResult": {
                "statusText": "failed",
                "isReturned": False,
                "returnValue": None,
                "failureReason": error_text,
                "turnCount": get_turn_count_from_event_list(event_list),
                "latestToolCall": latest_tool_call,
            },
            "latestToolCall": latest_tool_call,
        },
    )


def get_latest_subagent_request_event(db, parent_conversation_id: int):
    event_list = list_events_by_conversation(db, parent_conversation_id)
    for event_item in reversed(event_list):
        if get_is_subagent_tool_call_event(event_item):
            return event_item
    raise RuntimeError("subagent request event not found")


def lock_subagent_run(db, run_id: str, parent_conversation_id: int):
    with closing(db.cursor()) as cursor:
        cursor.execute(
            """
            select runId, statusText
            from subagent_run
            where runId = %s
              and parentConversationId = %s
            for update
            """,
            (run_id, parent_conversation_id),
        )
        row = cursor.fetchone()
    if not row:
        raise RuntimeError("subagent run not found")
    return {"runid": row[0], "statustext": row[1]}


def create_subagent_child_list(
    db,
    parent_conversation_id: int,
    run_id: str,
    item_list: list[dict[str, Any]],
    max_turns: int,
    request_event_id: int,
    timezone: int,
):
    child_list = []
    template = get_template_by_key("subagent-basic")
    for item in item_list:
        metadata = {
            "title": item["name"],
            "statusText": "active",
            "templateKey": template["key"],
            "templateName": template["name"],
            "isUserTurn": False,
            "subAgentRunId": run_id,
            "subAgentName": item["name"],
            "subAgentIndex": item["index"],
            "subAgentMaxTurns": max_turns,
            "subAgentInitialPrompt": item["initialPrompt"],
            "subAgentParentToolCallEventId": str(request_event_id),
        }
        conversation = create_conversation_in_db(db, metadata, timezone, parent_conversation_id)
        child_conversation_id = int(conversation["conversationId"])
        mark_child_template_start_ready(db, child_conversation_id, timezone)
        insert_subagent_run_child(db, run_id, parent_conversation_id, child_conversation_id, item)
        child_list.append({
            "conversationId": str(child_conversation_id),
            "name": item["name"],
            "index": item["index"],
            "statusText": "running",
            "turnCount": 0,
            "latestToolCall": None,
        })
    return child_list


def mark_child_template_start_ready(db, conversation_id: int, timezone: int):
    with closing(db.cursor()) as cursor:
        cursor.execute(
            """
            update conversation
            set stateCode = %s,
                execStatusCode = %s,
                updateAt = now(),
                updateAtTimezone = %s
            where id = %s
            """,
            (STATE_TEMPLATE_START_READY, EXEC_STATUS_PENDING, timezone, conversation_id),
        )


def insert_subagent_run_child(db, run_id: str, parent_conversation_id: int, child_conversation_id: int, item: dict[str, Any]):
    with closing(db.cursor()) as cursor:
        cursor.execute(
            """
            insert into subagent_run_child(
                runId,
                childConversationId,
                parentConversationId,
                childIndex,
                nameText,
                statusText,
                updateAt
            )
            values (%s, %s, %s, %s, %s, %s, now())
            """,
            (run_id, child_conversation_id, parent_conversation_id, int(item["index"]), item["name"], "running"),
        )


def update_subagent_run_started(db, run_id: str, event_start_id: int, child_count: int):
    with closing(db.cursor()) as cursor:
        cursor.execute(
            """
            update subagent_run
            set startEventId = %s,
                statusText = %s,
                childCount = %s,
                updateAt = now()
            where runId = %s
            """,
            (event_start_id, "running", child_count, run_id),
        )


def build_parent_subagent_run_metadata(db, parent_conversation_id: int, run_id: str, event_start: dict[str, Any], child_list: list[dict[str, Any]]):
    conversation = get_conversation_by_id(db, parent_conversation_id)
    metadata_parent = normalize_metadata(conversation["metadata"])
    run_by_id = metadata_parent.get("subAgentRunById") if isinstance(metadata_parent.get("subAgentRunById"), dict) else {}
    run_by_id[run_id] = {
        "statusText": "running",
        "childConversationIdList": [child["conversationId"] for child in child_list],
        "startEventId": str(event_start["id"]),
        "resultEventId": "",
    }
    return {
        "childConversationIdList": metadata_parent["childConversationIdList"],
        "subAgentRunById": run_by_id,
        "isUserTurn": False,
    }


def get_parent_template_key(db, parent_conversation_id: int):
    conversation = get_conversation_by_id(db, parent_conversation_id)
    metadata = normalize_metadata(conversation["metadata"])
    return str(metadata.get("templateKey") or "free-talk")


def build_subagent_event_content(kind: str, data: dict[str, Any]):
    return {
        "metadata": {
            "schemaVersion": 1,
            "kind": kind,
        },
        "data": [
            {
                "type": "json",
                "data": data,
            },
        ],
    }


def build_subagent_child_finish_result(data: dict[str, Any], event_list_new: list[dict[str, Any]]):
    metadata_child = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    latest_tool_call = get_latest_tool_call_summary(event_list_new)
    child_result = get_subagent_result_from_event_list(event_list_new, latest_tool_call)
    return {
        "metadataChild": metadata_child,
        "childResult": child_result,
        "latestToolCall": latest_tool_call,
        "metadataUpdate": {
            "statusText": "completed" if child_result.get("isReturned") is True else "failed",
            "isUserTurn": False,
            "endStatusText": "completed" if child_result.get("isReturned") is True else "abnormal",
            "subAgentResult": child_result,
        },
        "stateCodeNext": STATE_COMPLETED if child_result.get("isReturned") is True else STATE_FAILED,
        "execStatusCodeNext": EXEC_STATUS_IDLE,
    }


def get_subagent_result_from_event_list(event_list: list[dict[str, Any]], latest_tool_call: dict[str, Any] | None):
    for event_item in reversed(event_list):
        if event_item.get("subtypeText") != "subAgentReturn":
            continue
        content_json = event_item.get("contentJson") if isinstance(event_item.get("contentJson"), dict) else {}
        return {
            "statusText": str(content_json.get("statusText") or "completed"),
            "isReturned": content_json.get("isReturned") is True,
            "returnValue": content_json.get("returnValue"),
            "failureReason": str(content_json.get("failureReason") or ""),
            "turnCount": int(content_json.get("turnCount") or 0),
            "latestToolCall": latest_tool_call,
        }
    return {
        "statusText": "failed",
        "isReturned": False,
        "returnValue": None,
        "failureReason": "subagent did not return a result",
        "turnCount": 0,
        "latestToolCall": latest_tool_call,
    }


def get_latest_tool_call_summary(event_list: list[dict[str, Any]]):
    for event_item in reversed(event_list):
        if event_item.get("subtypeText") != "toolCall":
            continue
        content_json = event_item.get("contentJson") if isinstance(event_item.get("contentJson"), dict) else {}
        return {
            "toolName": str(content_json.get("tool_name") or ""),
            "args": content_json.get("args") if isinstance(content_json.get("args"), dict) else {},
        }
    return None


def get_turn_count_from_event_list(event_list: list[dict[str, Any]]):
    return len([event for event in event_list if event.get("typeText") == "agentMessage"])


def get_subagent_run_summary(db, run_id: str):
    with closing(db.cursor()) as cursor:
        cursor.execute(
            """
            select
              childConversationId,
              childIndex,
              nameText,
              statusText,
              turnCount,
              latestToolCallJson,
              returnJson,
              failureText
            from subagent_run_child
            where runId = %s
            order by childIndex asc, childConversationId asc
            """,
            (run_id,),
        )
        row_list = cursor.fetchall() or []
    child_list = []
    for row in row_list:
        return_json = row[6] if isinstance(row[6], dict) else {}
        child_list.append({
            "conversationId": str(row[0]),
            "index": int(row[1] or 0),
            "name": str(row[2] or ""),
            "statusText": str(row[3] or ""),
            "isReturned": return_json.get("isReturned") is True,
            "returnValue": return_json.get("returnValue"),
            "failureReason": str(row[7] or return_json.get("failureReason") or ""),
            "turnCount": int(row[4] or 0),
            "latestToolCall": row[5] if isinstance(row[5], dict) else None,
        })
    child_count = len(child_list)
    child_terminal_count = len([item for item in child_list if item["statusText"] in {"completed", "failed", "archived"}])
    child_success_count = len([item for item in child_list if item["statusText"] == "completed" and item["isReturned"] is True])
    child_failure_count = child_terminal_count - child_success_count
    if child_terminal_count < child_count:
        status_text = "running"
    elif child_success_count == child_count:
        status_text = "success"
    elif child_success_count == 0:
        status_text = "failed"
    else:
        status_text = "partialFailed"
    return {
        "statusText": status_text,
        "childCount": child_count,
        "childTerminalCount": child_terminal_count,
        "childSuccessCount": child_success_count,
        "childFailureCount": child_failure_count,
        "subagents": child_list,
    }


def update_subagent_run_counts(db, run_id: str, summary: dict[str, Any]):
    with closing(db.cursor()) as cursor:
        cursor.execute(
            """
            update subagent_run
            set statusText = %s,
                childTerminalCount = %s,
                childSuccessCount = %s,
                childFailureCount = %s,
                updateAt = now()
            where runId = %s
            """,
            (
                summary["statusText"],
                int(summary["childTerminalCount"]),
                int(summary["childSuccessCount"]),
                int(summary["childFailureCount"]),
                run_id,
            ),
        )


def create_subagent_result_event(db, parent_conversation_id: int, run_id: str, summary: dict[str, Any], timezone: int):
    result_data = {
        "statusText": summary["statusText"],
        "parentConversationId": str(parent_conversation_id),
        "subAgentRunId": run_id,
        "subagents": summary["subagents"],
    }
    child_id_list = [item["conversationId"] for item in summary["subagents"]]
    return create_event_in_db(
        db,
        parent_conversation_id,
        "orchestratorMessage",
        "subAgentResult",
        3,
        json.dumps(result_data, ensure_ascii=False),
        build_subagent_event_content("subAgentResult", result_data),
        {
            "templateKey": get_parent_template_key(db, parent_conversation_id),
            "toolName": TOOL_NAME_SUBAGENT,
            "subAgentRunId": run_id,
            "childConversationIdList": child_id_list,
        },
        timezone,
    )


def wake_parent_for_subagent_result(
    db,
    parent_conversation_id: int,
    run_id: str,
    result_event_id: int,
    summary: dict[str, Any],
    timezone: int,
):
    conversation = get_conversation_by_id(db, parent_conversation_id)
    metadata_parent = normalize_metadata(conversation["metadata"])
    run_by_id = metadata_parent.get("subAgentRunById") if isinstance(metadata_parent.get("subAgentRunById"), dict) else {}
    run_data = run_by_id.get(run_id) if isinstance(run_by_id.get(run_id), dict) else {}
    run_by_id[run_id] = {
        **run_data,
        "statusText": summary["statusText"],
        "resultEventId": str(result_event_id),
    }
    metadata_parent["subAgentRunById"] = run_by_id
    metadata_parent["isUserTurn"] = False
    with closing(db.cursor()) as cursor:
        cursor.execute(
            """
            update subagent_run
            set resultEventId = %s,
                statusText = %s,
                updateAt = now()
            where runId = %s
            """,
            (result_event_id, summary["statusText"], run_id),
        )
        cursor.execute(
            """
            update conversation
            set metadata = %s::jsonb,
                stateCode = %s,
                execStatusCode = %s,
                leaseId = null,
                leaseWorkerId = null,
                leaseExpireAt = null,
                leaseRetryCount = 0,
                leaseRetryAfterAt = null,
                version = version + 1,
                updateAt = now(),
                updateAtTimezone = %s
            where id = %s
            """,
            (
                json.dumps(metadata_parent),
                STATE_TOOL_RESULT_READY,
                EXEC_STATUS_PENDING,
                timezone,
                parent_conversation_id,
            ),
        )
        cursor.execute("select pg_notify(%s, '')", (CHANNEL_TASK_READY,))


def _to_text(value: Any):
    return str(value or "").strip()
