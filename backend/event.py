from __future__ import annotations

import json
from contextlib import closing
from typing import Any

from flask import request

from config import load_content_type_config
from conversation import normalize_metadata
from db import dict_cursor, run_in_transaction
from id_service import create_ms48_id
from login import has_request_permission


def _to_text(value: Any):
    return str(value or "").strip()


def _normalize_timezone(value: Any):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalize_optional_int(value: Any):
    if value is None or _to_text(value) == "":
        return None
    return int(value)


def _normalize_content_type(value: Any):
    content_type = int(value or 1)
    config = load_content_type_config()
    content_type_by_code = config.get("contentTypeByCode") if isinstance(config, dict) else {}
    if str(content_type) not in {str(key) for key in content_type_by_code.keys()}:
        raise RuntimeError("content type is not supported")
    return content_type


def _validate_content(content_type: int, content_text: Any, content_json: Any):
    if content_type == 1 and not _to_text(content_text):
        raise RuntimeError("contentText is required")
    if content_type == 2 and content_json is None:
        raise RuntimeError("contentJson is required")
    if content_type == 3 and not _to_text(content_text) and content_json is None:
        raise RuntimeError("contentText or contentJson is required")


def row_to_event(row):
    return {
        "id": str(row["id"]),
        "conversationId": str(row["conversationid"]),
        "typeCode": row["typecode"],
        "typeText": str(row["typetext"] or ""),
        "subtypeCode": row["subtypecode"],
        "subtypeText": str(row["subtypetext"] or ""),
        "contentType": int(row["contenttype"]),
        "contentText": row["contenttext"],
        "contentJson": row["contentjson"],
        "metadata": row["metadata"] if isinstance(row["metadata"], dict) else {},
        "createAt": str(row["createat"] or ""),
        "createAtTimezone": row["createattimezone"],
        "updateAt": str(row["updateat"] or ""),
        "updateAtTimezone": row["updateattimezone"],
    }


def _load_conversation_metadata_for_update(cursor, conversation_id: int):
    cursor.execute("select metadata from conversation where id = %s for update", (conversation_id,))
    row = cursor.fetchone()
    if not row:
        raise RuntimeError("conversation not found")
    return normalize_metadata(row["metadata"])


def create_event_in_db(
    db,
    conversation_id: int,
    type_text: str,
    subtype_text: str,
    content_type: int,
    content_text: Any,
    content_json: Any,
    metadata: Any,
    timezone: int,
    type_code: int | None = None,
    subtype_code: int | None = None,
):
    normalized_type_text = _to_text(type_text)
    normalized_subtype_text = _to_text(subtype_text) or "textSimple"
    if not normalized_type_text:
        raise RuntimeError("typeText is required")
    normalized_content_type = _normalize_content_type(content_type)
    _validate_content(normalized_content_type, content_text, content_json)
    event_id = create_ms48_id()
    event_id_text = str(event_id)
    metadata_event = dict(metadata) if isinstance(metadata, dict) else {}

    with closing(dict_cursor(db)) as cursor:
        metadata_conversation = _load_conversation_metadata_for_update(cursor, conversation_id)
        evet_list = metadata_conversation["evetList"]
        evet_list.append(event_id_text)
        metadata_conversation["evetList"] = evet_list
        cursor.execute(
            """
            insert into event(
                id,
                conversationId,
                typeCode,
                typeText,
                subtypeCode,
                subtypeText,
                contentType,
                contentText,
                contentJson,
                metadata,
                createAtTimezone,
                updateAtTimezone
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
            """,
            (
                event_id,
                conversation_id,
                type_code,
                normalized_type_text,
                subtype_code,
                normalized_subtype_text,
                normalized_content_type,
                content_text,
                json.dumps(content_json) if content_json is not None else None,
                json.dumps(metadata_event),
                timezone,
                timezone,
            ),
        )
        cursor.execute(
            """
            update conversation
            set metadata = %s::jsonb,
                updateAt = now(),
                updateAtTimezone = %s
            where id = %s
            """,
            (json.dumps(metadata_conversation), timezone, conversation_id),
        )
        cursor.execute(
            """
            select id, conversationId, typeCode, typeText, subtypeCode, subtypeText,
                   contentType, contentText, contentJson, metadata,
                   createAt, createAtTimezone, updateAt, updateAtTimezone
            from event
            where id = %s
            """,
            (event_id,),
        )
        row = cursor.fetchone()
    return row_to_event(row)


def get_event_by_id(db, event_id: int):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            """
            select id, conversationId, typeCode, typeText, subtypeCode, subtypeText,
                   contentType, contentText, contentJson, metadata,
                   createAt, createAtTimezone, updateAt, updateAtTimezone
            from event
            where id = %s
            limit 1
            """,
            (event_id,),
        )
        row = cursor.fetchone()
    if not row:
        raise RuntimeError("event not found")
    return row_to_event(row)


def list_events_by_conversation(db, conversation_id: int):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute("select metadata from conversation where id = %s", (conversation_id,))
        conversation_row = cursor.fetchone()
        if not conversation_row:
            raise RuntimeError("conversation not found")
        evet_list = normalize_metadata(conversation_row["metadata"])["evetList"]
        event_id_list = [int(item) for item in evet_list if _to_text(item)]
        if not event_id_list:
            return []
        cursor.execute(
            """
            select id, conversationId, typeCode, typeText, subtypeCode, subtypeText,
                   contentType, contentText, contentJson, metadata,
                   createAt, createAtTimezone, updateAt, updateAtTimezone
            from event
            where conversationId = %s and id = any(%s)
            """,
            (conversation_id, event_id_list),
        )
        row_list = cursor.fetchall() or []
    event_by_id = {str(row["id"]): row_to_event(row) for row in row_list}
    return [event_by_id[event_id_text] for event_id_text in evet_list if event_id_text in event_by_id]


def register_event_routes(app, make_json_response):
    @app.post("/api/event/create")
    def event_create():
        if not has_request_permission("W"):
            return make_json_response(-1, message="write permission required"), 403
        body = request.get_json(silent=True) or {}
        conversation_id = _to_text(body.get("conversationId"))
        if not conversation_id:
            return make_json_response(-10, message="conversationId is required"), 400
        timezone = _normalize_timezone(body.get("timezone"))

        def action(db):
            return create_event_in_db(
                db,
                int(conversation_id),
                body.get("typeText"),
                body.get("subtypeText"),
                body.get("contentType") or 1,
                body.get("contentText"),
                body.get("contentJson"),
                body.get("metadata"),
                timezone,
                _normalize_optional_int(body.get("typeCode")),
                _normalize_optional_int(body.get("subtypeCode")),
            )

        try:
            return make_json_response(0, data=run_in_transaction(action))
        except Exception as error:
            return make_json_response(-1, message=str(error)), 500

    @app.get("/api/event/list")
    @app.post("/api/event/list")
    def event_list():
        if not has_request_permission("R"):
            return make_json_response(-1, message="read permission required"), 403
        body = (request.get_json(silent=True) or {}) if request.method == "POST" else {}
        conversation_id = _to_text(body.get("conversationId") if request.method == "POST" else request.args.get("conversationId"))
        if not conversation_id:
            return make_json_response(
                0,
                data={
                    "conversationId": "",
                    "pageIndex": 1,
                    "pageSize": 0,
                    "totalCount": 0,
                    "items": [],
                },
            )
        try:
            page_index_raw = body.get("pageIndex") if request.method == "POST" else request.args.get("pageIndex")
            page_index = max(1, int(page_index_raw or 1))
        except (TypeError, ValueError):
            page_index = 1
        try:
            page_size_raw = body.get("pageSize") if request.method == "POST" else request.args.get("pageSize")
            page_size = max(1, min(500, int(page_size_raw or 100)))
        except (TypeError, ValueError):
            page_size = 100

        def action(db):
            item_list = list_events_by_conversation(db, int(conversation_id))
            start_index = (page_index - 1) * page_size
            return {
                "conversationId": conversation_id,
                "pageIndex": page_index,
                "pageSize": page_size,
                "totalCount": len(item_list),
                "items": item_list[start_index:start_index + page_size],
            }

        try:
            return make_json_response(0, data=run_in_transaction(action))
        except Exception as error:
            return make_json_response(-1, message=str(error)), 500

    @app.get("/api/event/get")
    def event_get():
        if not has_request_permission("R"):
            return make_json_response(-1, message="read permission required"), 403
        event_id = _to_text(request.args.get("id"))
        if not event_id:
            return make_json_response(-10, message="id is required"), 400

        def action(db):
            return get_event_by_id(db, int(event_id))

        try:
            return make_json_response(0, data=run_in_transaction(action))
        except Exception as error:
            return make_json_response(-1, message=str(error)), 500

    @app.post("/api/event/update")
    def event_update():
        if not has_request_permission("W"):
            return make_json_response(-1, message="write permission required"), 403
        body = request.get_json(silent=True) or {}
        event_id = _to_text(body.get("id"))
        if not event_id:
            return make_json_response(-10, message="id is required"), 400
        timezone = _normalize_timezone(body.get("timezone"))

        def action(db):
            content_type = _normalize_content_type(body.get("contentType") or 1)
            _validate_content(content_type, body.get("contentText"), body.get("contentJson"))
            with closing(db.cursor()) as cursor:
                cursor.execute(
                    """
                    update event
                    set contentType = %s,
                        contentText = %s,
                        contentJson = %s::jsonb,
                        metadata = %s::jsonb,
                        updateAt = now(),
                        updateAtTimezone = %s
                    where id = %s
                    """,
                    (
                        content_type,
                        body.get("contentText"),
                        json.dumps(body.get("contentJson")) if body.get("contentJson") is not None else None,
                        json.dumps(body.get("metadata") if isinstance(body.get("metadata"), dict) else {}),
                        timezone,
                        int(event_id),
                    ),
                )
                if cursor.rowcount < 1:
                    raise RuntimeError("event not found")
            return get_event_by_id(db, int(event_id))

        try:
            return make_json_response(0, data=run_in_transaction(action))
        except Exception as error:
            return make_json_response(-1, message=str(error)), 500

    @app.post("/api/event/delete")
    def event_delete():
        if not has_request_permission("W"):
            return make_json_response(-1, message="write permission required"), 403
        body = request.get_json(silent=True) or {}
        event_id = _to_text(body.get("id"))
        if not event_id:
            return make_json_response(-10, message="id is required"), 400
        timezone = _normalize_timezone(body.get("timezone"))

        def action(db):
            with closing(dict_cursor(db)) as cursor:
                cursor.execute("select conversationId from event where id = %s", (int(event_id),))
                event_row = cursor.fetchone()
                if not event_row:
                    raise RuntimeError("event not found")
                conversation_id = int(event_row["conversationid"])
                metadata_conversation = _load_conversation_metadata_for_update(cursor, conversation_id)
                metadata_conversation["evetList"] = [
                    item for item in metadata_conversation["evetList"] if str(item) != event_id
                ]
                cursor.execute("delete from event where id = %s", (int(event_id),))
                cursor.execute(
                    """
                    update conversation
                    set metadata = %s::jsonb,
                        updateAt = now(),
                        updateAtTimezone = %s
                    where id = %s
                    """,
                    (json.dumps(metadata_conversation), timezone, conversation_id),
                )
            return {"id": event_id, "conversationId": str(conversation_id)}

        try:
            return make_json_response(0, data=run_in_transaction(action))
        except Exception as error:
            return make_json_response(-1, message=str(error)), 500
