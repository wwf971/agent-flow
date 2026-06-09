from __future__ import annotations

import json
from contextlib import closing
from typing import Any

from flask import request

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


def _normalize_bool(value: Any):
    if isinstance(value, bool):
        return value
    text = _to_text(value).lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    return False


def _has_conversation_trashbin_column(db):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            """
            select 1
            from information_schema.columns
            where table_schema = current_schema()
              and table_name = 'conversation'
              and lower(column_name) = 'isintrashbin'
            limit 1
            """
        )
        return cursor.fetchone() is not None


def _get_conversation_select_sql(db):
    trashbin_select = "isInTrashbin" if _has_conversation_trashbin_column(db) else "false as isInTrashbin"
    return f"id, metadata, {trashbin_select}, createAt, createAtTimezone, updateAt, updateAtTimezone"


def normalize_metadata(metadata: Any):
    data = dict(metadata) if isinstance(metadata, dict) else {}
    evet_list = data.get("evetList")
    if not isinstance(evet_list, list):
        evet_list = []
    data["evetList"] = [str(item) for item in evet_list if str(item or "").strip()]
    return data


def row_to_conversation(row):
    metadata = normalize_metadata(row["metadata"])
    return {
        "conversationId": str(row["id"]),
        "metadata": metadata,
        "isInTrashbin": bool(row.get("isintrashbin")),
        "createAt": str(row["createat"] or ""),
        "createAtTimezone": row["createattimezone"],
        "updateAt": str(row["updateat"] or ""),
        "updateAtTimezone": row["updateattimezone"],
    }


def create_conversation_in_db(db, metadata: Any, timezone: int):
    conversation_id = create_ms48_id()
    metadata_normalized = normalize_metadata(metadata)
    with closing(db.cursor()) as cursor:
        cursor.execute(
            """
            insert into conversation(
                id,
                metadata,
                createAtTimezone,
                updateAtTimezone
            )
            values (%s, %s::jsonb, %s, %s)
            """,
            (conversation_id, json.dumps(metadata_normalized), timezone, timezone),
        )
    return {
        "conversationId": str(conversation_id),
        "metadata": metadata_normalized,
    }


def normalize_conversation_metadata_for_create(metadata: Any):
    metadata_normalized = normalize_metadata(metadata)
    metadata_normalized["templateKey"] = str(metadata_normalized.get("templateKey") or "free-talk")
    metadata_normalized["templateName"] = str(metadata_normalized.get("templateName") or "Free Talk")
    metadata_normalized["statusText"] = str(metadata_normalized.get("statusText") or "active")
    if "isUserTurn" not in metadata_normalized:
        metadata_normalized["isUserTurn"] = True
    return metadata_normalized


def get_conversation_by_id(db, conversation_id: int):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            f"""
            select {_get_conversation_select_sql(db)}
            from conversation
            where id = %s
            limit 1
            """,
            (conversation_id,),
        )
        row = cursor.fetchone()
    if not row:
        raise RuntimeError("conversation not found")
    return row_to_conversation(row)


def register_conversation_routes(app, make_json_response):
    @app.post("/api/conversation/create")
    def conversation_create():
        if not has_request_permission("W"):
            return make_json_response(-1, message="write permission required"), 403
        body = request.get_json(silent=True) or {}
        timezone = _normalize_timezone(body.get("timezone"))

        def action(db):
            return create_conversation_in_db(db, normalize_conversation_metadata_for_create(body.get("metadata")), timezone)

        try:
            return make_json_response(0, data=run_in_transaction(action))
        except Exception as error:
            return make_json_response(-1, message=str(error)), 500

    @app.get("/api/conversation/get")
    def conversation_get():
        if not has_request_permission("R"):
            return make_json_response(-1, message="read permission required"), 403
        conversation_id = _to_text(request.args.get("conversationId"))
        if not conversation_id:
            return make_json_response(-10, message="conversationId is required"), 400

        def action(db):
            return get_conversation_by_id(db, int(conversation_id))

        try:
            return make_json_response(0, data=run_in_transaction(action))
        except Exception as error:
            return make_json_response(-1, message=str(error)), 500

    @app.get("/api/conversation/list")
    @app.post("/api/conversation/list")
    def conversation_list():
        if not has_request_permission("R"):
            return make_json_response(-1, message="read permission required"), 403
        body = (request.get_json(silent=True) or {}) if request.method == "POST" else {}
        search_text = _to_text(body.get("searchText") if request.method == "POST" else request.args.get("searchText"))
        try:
            page_index_raw = body.get("pageIndex") if request.method == "POST" else request.args.get("pageIndex")
            page_index = max(1, int(page_index_raw or 1))
        except (TypeError, ValueError):
            page_index = 1
        try:
            page_size_raw = body.get("pageSize") if request.method == "POST" else request.args.get("pageSize")
            page_size = max(1, min(200, int(page_size_raw or 30)))
        except (TypeError, ValueError):
            page_size = 30

        def action(db):
            where_clause = ""
            params = []
            if search_text:
                where_clause = "where metadata::text ilike %s"
                params.append(f"%{search_text}%")
            with closing(dict_cursor(db)) as cursor:
                cursor.execute(f"select count(1) as totalCount from conversation {where_clause}", tuple(params))
                total_row = cursor.fetchone()
                total_count = int(total_row["totalcount"] if total_row else 0)
                cursor.execute(
                    f"""
                    select {_get_conversation_select_sql(db)}
                    from conversation
                    {where_clause}
                    order by updateAt desc, id desc
                    limit %s offset %s
                    """,
                    tuple(params + [page_size, (page_index - 1) * page_size]),
                )
                row_list = cursor.fetchall() or []
            return {
                "pageIndex": page_index,
                "pageSize": page_size,
                "totalCount": total_count,
                "items": [row_to_conversation(row) for row in row_list],
            }

        try:
            return make_json_response(0, data=run_in_transaction(action))
        except Exception as error:
            return make_json_response(-1, message=str(error)), 500

    @app.post("/api/conversation/rename")
    def conversation_rename():
        if not has_request_permission("W"):
            return make_json_response(-1, message="write permission required"), 403
        body = request.get_json(silent=True) or {}
        conversation_id = _to_text(body.get("conversationId"))
        title_text = _to_text(body.get("titleText"))
        if not conversation_id:
            return make_json_response(-10, message="conversationId is required"), 400
        if not title_text:
            return make_json_response(-10, message="titleText is required"), 400
        timezone = _normalize_timezone(body.get("timezone"))

        def action(db):
            with closing(dict_cursor(db)) as cursor:
                cursor.execute("select metadata from conversation where id = %s for update", (int(conversation_id),))
                row = cursor.fetchone()
                if not row:
                    raise RuntimeError("conversation not found")
                metadata_next = normalize_metadata(row["metadata"])
                metadata_next["title"] = title_text
                cursor.execute(
                    """
                    update conversation
                    set metadata = %s::jsonb,
                        updateAt = now(),
                        updateAtTimezone = %s
                    where id = %s
                    """,
                    (json.dumps(metadata_next), timezone, int(conversation_id)),
                )
            return get_conversation_by_id(db, int(conversation_id))

        try:
            return make_json_response(0, data=run_in_transaction(action))
        except Exception as error:
            return make_json_response(-1, message=str(error)), 500

    @app.post("/api/conversation/trashbin/update")
    def conversation_trashbin_update():
        if not has_request_permission("W"):
            return make_json_response(-1, message="write permission required"), 403
        body = request.get_json(silent=True) or {}
        conversation_id = _to_text(body.get("conversationId"))
        if not conversation_id:
            return make_json_response(-10, message="conversationId is required"), 400
        timezone = _normalize_timezone(body.get("timezone"))
        is_in_trashbin = _normalize_bool(body.get("isInTrashbin"))

        def action(db):
            if not _has_conversation_trashbin_column(db):
                raise RuntimeError("conversation.isInTrashbin column is missing. Run script/migrate_add_conversation_trashbin.py")
            with closing(db.cursor()) as cursor:
                cursor.execute(
                    """
                    update conversation
                    set isInTrashbin = %s,
                        updateAt = now(),
                        updateAtTimezone = %s
                    where id = %s
                    """,
                    (is_in_trashbin, timezone, int(conversation_id)),
                )
                if cursor.rowcount < 1:
                    raise RuntimeError("conversation not found")
            return get_conversation_by_id(db, int(conversation_id))

        try:
            return make_json_response(0, data=run_in_transaction(action))
        except Exception as error:
            return make_json_response(-1, message=str(error)), 500

    @app.post("/api/conversation/metadata/update")
    def conversation_metadata_update():
        if not has_request_permission("W"):
            return make_json_response(-1, message="write permission required"), 403
        body = request.get_json(silent=True) or {}
        conversation_id = _to_text(body.get("conversationId"))
        if not conversation_id:
            return make_json_response(-10, message="conversationId is required"), 400
        timezone = _normalize_timezone(body.get("timezone"))

        def action(db):
            with closing(dict_cursor(db)) as cursor:
                cursor.execute("select metadata from conversation where id = %s for update", (int(conversation_id),))
                row = cursor.fetchone()
                if not row:
                    raise RuntimeError("conversation not found")
                metadata_existing = normalize_metadata(row["metadata"])
                metadata_next = normalize_metadata(body.get("metadata"))
                metadata_next["evetList"] = metadata_existing["evetList"]
                cursor.execute(
                    """
                    update conversation
                    set metadata = %s::jsonb,
                        updateAt = now(),
                        updateAtTimezone = %s
                    where id = %s
                    """,
                    (json.dumps(metadata_next), timezone, int(conversation_id)),
                )
            return get_conversation_by_id(db, int(conversation_id))

        try:
            return make_json_response(0, data=run_in_transaction(action))
        except Exception as error:
            return make_json_response(-1, message=str(error)), 500

    @app.post("/api/conversation/delete")
    def conversation_delete():
        if not has_request_permission("W"):
            return make_json_response(-1, message="write permission required"), 403
        body = request.get_json(silent=True) or {}
        conversation_id = _to_text(body.get("conversationId"))
        if not conversation_id:
            return make_json_response(-10, message="conversationId is required"), 400

        def action(db):
            with closing(dict_cursor(db)) as cursor:
                cursor.execute("select id from conversation where id = %s for update", (int(conversation_id),))
                row = cursor.fetchone()
                if not row:
                    raise RuntimeError("conversation not found")
                cursor.execute("delete from event where conversationId = %s", (int(conversation_id),))
                event_delete_count = cursor.rowcount
                cursor.execute("delete from conversation where id = %s", (int(conversation_id),))
                if cursor.rowcount < 1:
                    raise RuntimeError("conversation not found")
            return {"conversationId": conversation_id, "eventDeleteCount": event_delete_count}

        try:
            return make_json_response(0, data=run_in_transaction(action))
        except Exception as error:
            return make_json_response(-1, message=str(error)), 500
