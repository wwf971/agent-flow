from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime, timedelta, timezone as datetime_timezone
from threading import Thread
from typing import Any

from flask import request

from conifg_template import get_template_by_key, iter_template_events, list_templates
from config import get_google_model_config
from conversation import create_conversation_in_db, get_conversation_by_id, normalize_metadata
from db import dict_cursor, run_in_transaction
from event import create_event_in_db, list_events_by_conversation
from login import has_request_permission


def _to_text(value: Any):
    return str(value or "").strip()


def _normalize_timezone(value: Any):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _build_time_stamp(timezone_value: int):
    timezone_info = datetime_timezone(timedelta(minutes=timezone_value))
    time_value = datetime.now(timezone_info)
    centisecond = time_value.microsecond // 10000
    offset_hour = timezone_value // 60
    offset_sign = "+" if offset_hour >= 0 else "-"
    return f"{time_value:%Y%m%d_%H%M%S}{centisecond:02d}{offset_sign}{abs(offset_hour):02d}"


def _build_default_conversation_title(template_name: str, timezone_value: int):
    return f"{template_name} {_build_time_stamp(timezone_value)}"


def _build_prompt_from_events(event_list: list[dict[str, Any]], message_text: str):
    line_list = ["You are a helpful assistant."]
    for event in event_list:
        type_text = _to_text(event.get("typeText"))
        subtype_text = _to_text(event.get("subtypeText"))
        content_text = _to_text(event.get("contentText"))
        if subtype_text != "textSimple" or not content_text:
            continue
        if type_text == "userMessage":
            line_list.append(f"User: {content_text}")
        elif type_text == "agentMessage":
            line_list.append(f"Assistant: {content_text}")
        elif type_text == "orchestratorMessage":
            line_list.append(f"Orchestrator: {content_text}")
    line_list.append(f"User: {message_text}")
    return "\n".join(line_list)


def call_agent_text(event_list: list[dict[str, Any]], message_text: str):
    model_config = get_google_model_config()
    api_key = model_config["apiKey"]
    model_name = model_config["model"]
    if not api_key:
        raise RuntimeError("google api key is not configured")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=_build_prompt_from_events(event_list, message_text),
        config=types.GenerateContentConfig(temperature=0.0),
    )
    return response.text or ""


def _update_conversation_metadata(db, conversation_id: int, metadata_update: dict[str, Any], timezone: int):
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
                updateAt = now(),
                updateAtTimezone = %s
            where id = %s
            """,
            (json.dumps(metadata_next), timezone, conversation_id),
        )
    return metadata_next


def _get_template_key_from_conversation(db, conversation_id: int):
    conversation = get_conversation_by_id(db, conversation_id)
    metadata = normalize_metadata(conversation.get("metadata"))
    return str(metadata.get("templateKey") or "free-talk")


def _get_conversation_turn_state(db, conversation_id: int):
    conversation = get_conversation_by_id(db, conversation_id)
    metadata = normalize_metadata(conversation.get("metadata"))
    return {
        "templateKey": str(metadata.get("templateKey") or "free-talk"),
        "statusText": str(metadata.get("statusText") or "active"),
        "isUserTurn": metadata.get("isUserTurn") is not False,
        "isInTrashbin": conversation.get("isInTrashbin") is True,
    }


def _create_backend_exception_event(db, conversation_id: int, error: Exception, timezone: int):
    event_error = create_event_in_db(
        db,
        conversation_id,
        "EndAbnormal",
        "BackendException",
        1,
        str(error),
        None,
        {"errorText": str(error)},
        timezone,
    )
    _update_conversation_metadata(
        db,
        conversation_id,
        {
            "statusText": "failed",
            "isUserTurn": False,
            "endStatusText": "abnormal",
        },
        timezone,
    )
    return event_error


def _create_generated_event(db, conversation_id: int, event_item: dict[str, Any], timezone: int):
    return create_event_in_db(
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


def _get_template_start_finish_metadata(template_key: str):
    if template_key == "mcp-interactive":
        return {
            "statusText": "active",
            "isUserTurn": True,
        }
    return {
        "statusText": "completed",
        "isUserTurn": False,
        "endStatusText": "completed",
    }


def _get_turn_finish_metadata(event_generated_list: list[dict[str, Any]]):
    for event_item in event_generated_list:
        metadata = event_item.get("metadata") if isinstance(event_item.get("metadata"), dict) else {}
        content_json = event_item.get("contentJson") if isinstance(event_item.get("contentJson"), dict) else {}
        if metadata.get("toolName") == "tool_terminate_conversation" or content_json.get("is_terminated") is True:
            return {
                "statusText": "completed",
                "isUserTurn": False,
                "endStatusText": "completed",
                "endReasonText": str(content_json.get("reason") or ""),
            }
    return {"isUserTurn": True}


def _is_template_start_background(template_key: str):
    return template_key in {"mcp-tool-all", "mcp-interactive"}


def _run_template_start_background(template_key: str, conversation_id: int, timezone: int):
    try:
        event_iter = iter_template_events(
            template_key,
            {
                "conversationId": str(conversation_id),
                "messageText": "",
                "eventList": [],
                "logDir": None,
            },
        )
        for event_item in event_iter:
            run_in_transaction(
                lambda db, event_item_current=event_item: _create_generated_event(
                    db,
                    conversation_id,
                    event_item_current,
                    timezone,
                )
            )

        def finish_action(db):
            _update_conversation_metadata(
                db,
                conversation_id,
                _get_template_start_finish_metadata(template_key),
                timezone,
            )
            return True

        run_in_transaction(finish_action)
    except Exception as error:
        try:
            run_in_transaction(lambda db: _create_backend_exception_event(db, conversation_id, error, timezone))
        except Exception:
            pass


def _start_template_background_thread(template_key: str, conversation_id: int, timezone: int):
    thread = Thread(
        target=_run_template_start_background,
        args=(template_key, conversation_id, timezone),
        daemon=True,
    )
    thread.start()


def _run_turn_background(template_key: str, conversation_id: int, message_text: str, event_list: list[dict[str, Any]], timezone: int):
    try:
        if template_key == "free-talk":
            reply_text = call_agent_text(event_list[:-1], message_text)
            event_generated_list = [
                {
                    "typeText": "agentMessage",
                    "subtypeText": "textSimple",
                    "contentType": 1,
                    "contentText": reply_text,
                    "metadata": {"templateKey": "free-talk"},
                }
            ]
        else:
            event_generated_list = list(
                iter_template_events(
                    template_key,
                    {
                        "conversationId": str(conversation_id),
                        "messageText": message_text,
                        "eventList": event_list,
                        "logDir": None,
                    },
                )
            )

        def create_agent_event_action(db):
            event_created_list = []
            for event_item in event_generated_list:
                event_created = _create_generated_event(db, conversation_id, event_item, timezone)
                event_created_list.append(event_created)
            _update_conversation_metadata(db, conversation_id, _get_turn_finish_metadata(event_generated_list), timezone)
            return True

        run_in_transaction(create_agent_event_action)
    except Exception as error:
        try:
            run_in_transaction(lambda db: _create_backend_exception_event(db, conversation_id, error, timezone))
        except Exception:
            pass


def _start_turn_background_thread(template_key: str, conversation_id: int, message_text: str, event_list: list[dict[str, Any]], timezone: int):
    thread = Thread(
        target=_run_turn_background,
        args=(template_key, conversation_id, message_text, event_list, timezone),
        daemon=True,
    )
    thread.start()


def register_orchestrator_routes(app, make_json_response):
    @app.get("/api/template/list")
    @app.post("/api/template/list")
    def template_list():
        if not has_request_permission("R"):
            return make_json_response(-1, message="read permission required"), 403
        return make_json_response(0, data={"items": list_templates()})

    @app.post("/api/conversation/create/from-template")
    def conversation_create_from_template():
        if not has_request_permission("W"):
            return make_json_response(-1, message="write permission required"), 403
        body = request.get_json(silent=True) or {}
        timezone = _normalize_timezone(body.get("timezone"))
        template_key = _to_text(body.get("templateKey")) or "free-talk"
        template = get_template_by_key(template_key)
        metadata_raw = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
        metadata = {
            **metadata_raw,
            "title": metadata_raw.get("title") or _build_default_conversation_title(template["name"], timezone),
            "statusText": metadata_raw.get("statusText") or ("starting" if _is_template_start_background(template["key"]) else "active"),
            "templateKey": template["key"],
            "templateName": template["name"],
            "isUserTurn": not _is_template_start_background(template["key"]),
        }

        def action(db):
            return create_conversation_in_db(db, metadata, timezone)

        conversation_id_for_error = 0
        conversation = None
        try:
            conversation = run_in_transaction(action)
            conversation_id = int(conversation["conversationId"])
            conversation_id_for_error = conversation_id
            event_created_list = []
            if _is_template_start_background(template["key"]):
                _start_template_background_thread(template["key"], conversation_id, timezone)
            return make_json_response(
                0,
                data={
                    **conversation,
                    "eventGeneratedList": event_created_list,
                },
            )
        except Exception as error:
            if not conversation_id_for_error:
                return make_json_response(-1, message=str(error)), 500

            def create_error_event_action(db):
                event_error = _create_backend_exception_event(db, conversation_id_for_error, error, timezone)
                conversation_failed = get_conversation_by_id(db, conversation_id_for_error)
                return {
                    **conversation_failed,
                    "eventGeneratedList": [event_error],
                    "eventEndAbnormal": event_error,
                }

            try:
                data = run_in_transaction(create_error_event_action)
                return make_json_response(-30, data=data, message=str(error)), 500
            except Exception:
                data = conversation or {"conversationId": str(conversation_id_for_error)}
                return make_json_response(-30, data=data, message=str(error)), 500

    @app.post("/api/orchestrator/turn/create")
    def orchestrator_turn_create():
        if not has_request_permission("W"):
            return make_json_response(-1, message="write permission required"), 403
        body = request.get_json(silent=True) or {}
        message_text = _to_text(body.get("messageText"))
        if not message_text:
            return make_json_response(-10, message="messageText is required"), 400
        timezone = _normalize_timezone(body.get("timezone"))
        conversation_id_text = _to_text(body.get("conversationId"))
        conversation_id_for_error = int(conversation_id_text) if conversation_id_text else 0

        if conversation_id_for_error:
            try:
                turn_state = run_in_transaction(lambda db: _get_conversation_turn_state(db, conversation_id_for_error))
            except Exception as error:
                return make_json_response(-10, message=str(error)), 400
            if turn_state["templateKey"] == "mcp-tool-all":
                return make_json_response(
                    -10,
                    message="MCP Tool Exercise is a one-shot template and does not accept user messages after startup",
                ), 400
            if turn_state["isInTrashbin"]:
                return make_json_response(-10, message="conversation is in trashbin"), 400
            if turn_state["statusText"] != "active" or not turn_state["isUserTurn"]:
                return make_json_response(-10, message="conversation is not accepting user messages"), 400

        try:
            def create_user_event_action(db):
                nonlocal conversation_id_for_error
                if conversation_id_text:
                    conversation_id = int(conversation_id_text)
                else:
                    metadata_conversation = body.get("conversationMetadata")
                    if not isinstance(metadata_conversation, dict):
                        metadata_conversation = {}
                    template_key_new = str(metadata_conversation.get("templateKey") or "free-talk")
                    template = get_template_by_key(template_key_new)
                    metadata_conversation["templateKey"] = template["key"]
                    metadata_conversation["templateName"] = template["name"]
                    metadata_conversation["title"] = metadata_conversation.get("title") or _build_default_conversation_title(template["name"], timezone)
                    metadata_conversation["statusText"] = metadata_conversation.get("statusText") or "active"
                    metadata_conversation["isUserTurn"] = False
                    conversation = create_conversation_in_db(db, metadata_conversation, timezone)
                    conversation_id = int(conversation["conversationId"])
                conversation_id_for_error = conversation_id
                _update_conversation_metadata(db, conversation_id, {"isUserTurn": False}, timezone)
                event_user = create_event_in_db(
                    db,
                    conversation_id,
                    "userMessage",
                    "textSimple",
                    1,
                    message_text,
                    None,
                    body.get("metadata"),
                    timezone,
                )
                event_list = list_events_by_conversation(db, conversation_id)
                return {
                    "conversationId": str(conversation_id),
                    "eventUser": event_user,
                    "eventList": event_list,
                }

            user_result = run_in_transaction(create_user_event_action)
            conversation_id = int(user_result["conversationId"])
            template_key = run_in_transaction(lambda db: _get_template_key_from_conversation(db, conversation_id))
            _start_turn_background_thread(template_key, conversation_id, message_text, user_result["eventList"], timezone)
            return make_json_response(
                0,
                data={
                    "conversationId": str(conversation_id),
                    "eventUser": user_result["eventUser"],
                    "eventGeneratedList": [],
                    "eventAgent": None,
                },
            )
        except Exception as error:
            if not conversation_id_for_error:
                return make_json_response(-30, message=str(error)), 500
            try:
                conversation_id = conversation_id_for_error

                def create_error_event_action(db):
                    event_error = _create_backend_exception_event(db, conversation_id, error, timezone)
                    return {"conversationId": str(conversation_id), "eventOrchestrator": event_error}

                data = run_in_transaction(create_error_event_action)
                return make_json_response(-30, data=data, message=str(error)), 500
            except Exception:
                return make_json_response(-30, message=str(error)), 500
