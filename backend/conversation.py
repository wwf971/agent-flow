from __future__ import annotations

import json
from contextlib import closing
from typing import Any

from flask import request

from db import dict_cursor, run_in_transaction
from id_service import create_ms48_id
from lexorank import create_rank_list, get_rank_between, is_lexorank_valid, sort_ranked_items
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


def _has_conversation_rank_global_column(db):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            """
            select 1
            from information_schema.columns
            where table_schema = current_schema()
              and table_name = 'conversation'
              and lower(column_name) = 'rankglobal'
            limit 1
            """
        )
        return cursor.fetchone() is not None


def _has_conversation_parent_id_column(db):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            """
            select 1
            from information_schema.columns
            where table_schema = current_schema()
              and table_name = 'conversation'
              and lower(column_name) = 'parentid'
            limit 1
            """
        )
        return cursor.fetchone() is not None


def _has_conversation_iter_column(db):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            """
            select 1
            from information_schema.columns
            where table_schema = current_schema()
              and table_name = 'conversation'
              and lower(column_name) = 'statecode'
            limit 1
            """
        )
        return cursor.fetchone() is not None


def _get_conversation_select_sql(db):
    trashbin_select = "isInTrashbin" if _has_conversation_trashbin_column(db) else "false as isInTrashbin"
    rank_global_select = "rankGlobal" if _has_conversation_rank_global_column(db) else "null as rankGlobal"
    parent_id_select = "parentId" if _has_conversation_parent_id_column(db) else "null as parentId"
    iter_select = (
        "version, stateCode, execStatusCode, leaseId, leaseWorkerId, leaseExpireAt, leaseRetryCount, leaseRetryAfterAt"
        if _has_conversation_iter_column(db)
        else """
             0 as version,
             100 as stateCode,
             0 as execStatusCode,
             null as leaseId,
             null as leaseWorkerId,
             null as leaseExpireAt,
             0 as leaseRetryCount,
             null as leaseRetryAfterAt
        """
    )
    return f"id, metadata, {trashbin_select}, {rank_global_select}, {parent_id_select}, {iter_select}, createAt, createAtTimezone, updateAt, updateAtTimezone"


def normalize_metadata(metadata: Any):
    data = dict(metadata) if isinstance(metadata, dict) else {}
    event_list = data.get("eventList")
    if not isinstance(event_list, list):
        event_list = []
    data["eventList"] = [str(item) for item in event_list if str(item or "").strip()]
    child_conversation_id_list = data.get("childConversationIdList")
    if not isinstance(child_conversation_id_list, list):
        child_conversation_id_list = []
    data["childConversationIdList"] = [str(item) for item in child_conversation_id_list if str(item or "").strip()]
    return data


def row_to_conversation(row):
    metadata = normalize_metadata(row["metadata"])
    return {
        "conversationId": str(row["id"]),
        "metadata": metadata,
        "isInTrashbin": bool(row.get("isintrashbin")),
        "rankGlobal": str(row.get("rankglobal") or ""),
        "parentId": str(row.get("parentid") or ""),
        "version": int(row.get("version") or 0),
        "stateCode": int(row.get("statecode") or 100),
        "execStatusCode": int(row.get("execstatuscode") or 0),
        "leaseId": str(row.get("leaseid") or ""),
        "leaseWorkerId": str(row.get("leaseworkerid") or ""),
        "leaseExpireAt": str(row.get("leaseexpireat") or ""),
        "leaseRetryCount": int(row.get("leaseretrycount") or 0),
        "leaseRetryAfterAt": str(row.get("leaseretryafterat") or ""),
        "createAt": str(row["createat"] or ""),
        "createAtTimezone": row["createattimezone"],
        "updateAt": str(row["updateat"] or ""),
        "updateAtTimezone": row["updateattimezone"],
    }


def _get_rank_global_for_new_conversation(db, parent_id: int | None = None):
    if parent_id is not None:
        return ""
    if not _has_conversation_rank_global_column(db):
        return ""
    parent_filter_sql = "and parentId is null" if _has_conversation_parent_id_column(db) else ""
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            f"""
            select rankGlobal
            from conversation
            where isInTrashbin = false
              {parent_filter_sql}
              and rankGlobal ~ '^[0-9A-Za-z]{{12}}$'
            order by rankGlobal asc
            limit 1
            """
        )
        row = cursor.fetchone()
    rank_after = row["rankglobal"] if row else None
    rank_next = get_rank_between(None, rank_after)
    if rank_next:
        return rank_next
    _rebalance_present_conversation_ranks(db, [])
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            f"""
            select rankGlobal
            from conversation
            where isInTrashbin = false
              {parent_filter_sql}
              and rankGlobal ~ '^[0-9A-Za-z]{{12}}$'
            order by rankGlobal asc
            limit 1
            """
        )
        row = cursor.fetchone()
    return get_rank_between(None, row["rankglobal"] if row else None)


def _normalize_parent_id(value: Any):
    text = _to_text(value)
    return int(text) if text else None


def _append_child_conversation_id_to_parent(db, parent_id: int, child_conversation_id: int, timezone: int):
    with closing(dict_cursor(db)) as cursor:
        cursor.execute("select metadata from conversation where id = %s for update", (parent_id,))
        row = cursor.fetchone()
        if not row:
            raise RuntimeError("parent conversation not found")
        metadata_parent = normalize_metadata(row["metadata"])
        child_id_text = str(child_conversation_id)
        child_id_list = metadata_parent["childConversationIdList"]
        if child_id_text not in child_id_list:
            child_id_list.append(child_id_text)
        metadata_parent["childConversationIdList"] = child_id_list
        cursor.execute(
            """
            update conversation
            set metadata = %s::jsonb,
                updateAt = now(),
                updateAtTimezone = %s
            where id = %s
            """,
            (json.dumps(metadata_parent), timezone, parent_id),
        )
    return metadata_parent


def create_conversation_in_db(db, metadata: Any, timezone: int, parent_id: int | None = None):
    conversation_id = create_ms48_id()
    metadata_normalized = normalize_metadata(metadata)
    parent_id_normalized = _normalize_parent_id(parent_id)
    if parent_id_normalized is not None and not _has_conversation_parent_id_column(db):
        raise RuntimeError("conversation.parentId column is missing. Run script/_4_migrate_subagent.py")
    rank_global = _get_rank_global_for_new_conversation(db, parent_id_normalized)
    with closing(db.cursor()) as cursor:
        if _has_conversation_rank_global_column(db) and _has_conversation_parent_id_column(db):
            cursor.execute(
                """
                insert into conversation(
                    id,
                    metadata,
                    rankGlobal,
                    parentId,
                    createAtTimezone,
                    updateAtTimezone
                )
                values (%s, %s::jsonb, %s, %s, %s, %s)
                """,
                (conversation_id, json.dumps(metadata_normalized), rank_global, parent_id_normalized, timezone, timezone),
            )
        elif _has_conversation_rank_global_column(db):
            cursor.execute(
                """
                insert into conversation(
                    id,
                    metadata,
                    rankGlobal,
                    createAtTimezone,
                    updateAtTimezone
                )
                values (%s, %s::jsonb, %s, %s, %s)
                """,
                (conversation_id, json.dumps(metadata_normalized), rank_global, timezone, timezone),
            )
        else:
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
    if parent_id_normalized is not None:
        _append_child_conversation_id_to_parent(db, parent_id_normalized, conversation_id, timezone)
    return get_conversation_by_id(db, conversation_id)


def _get_present_conversation_rank_rows(db):
    if not _has_conversation_rank_global_column(db):
        raise RuntimeError("conversation.rankGlobal column is missing. Run script/_3_migrate_add_conversation_rank.py")
    parent_filter_sql = "and parentId is null" if _has_conversation_parent_id_column(db) else ""
    with closing(dict_cursor(db)) as cursor:
        cursor.execute(
            f"""
            select id, rankGlobal, updateAt
            from conversation
            where isInTrashbin = false
              {parent_filter_sql}
            order by updateAt desc, id desc
            for update
            """
        )
        row_list = cursor.fetchall() or []
    item_list = [
        {
            "id": str(row["id"]),
            "rankGlobal": str(row.get("rankglobal") or ""),
            "updateAt": str(row.get("updateat") or ""),
        }
        for row in row_list
    ]
    return sort_ranked_items(item_list)


def _rebalance_present_conversation_ranks(db, conversation_id_order_list: list[str] | None = None):
    row_list = _get_present_conversation_rank_rows(db)
    id_set_existing = {item["id"] for item in row_list}
    if conversation_id_order_list is None:
        conversation_id_list = [item["id"] for item in row_list]
    else:
        conversation_id_list = [item for item in conversation_id_order_list if item in id_set_existing]
        conversation_id_list.extend(item["id"] for item in row_list if item["id"] not in conversation_id_list)
    rank_list = create_rank_list(len(conversation_id_list))
    with closing(db.cursor()) as cursor:
        for conversation_id, rank_text in zip(conversation_id_list, rank_list):
            cursor.execute(
                """
                update conversation
                set rankGlobal = %s
                where id = %s
                """,
                (rank_text, int(conversation_id)),
            )
    return dict(zip(conversation_id_list, rank_list))


def _get_ranked_conversation_by_id(row_list: list[dict]):
    return {item["id"]: item for item in row_list}


def _get_valid_neighbor_rank(rank_by_id: dict[str, dict], conversation_id: str):
    if not conversation_id:
        return None
    rank_text = rank_by_id.get(conversation_id, {}).get("rankGlobal")
    return rank_text if is_lexorank_valid(rank_text) else None


def reorder_present_conversation_in_db(
    db,
    conversation_id: int,
    conversation_id_before: str,
    conversation_id_after: str,
    timezone: int,
):
    if _has_conversation_parent_id_column(db):
        with closing(dict_cursor(db)) as cursor:
            cursor.execute("select parentId from conversation where id = %s", (conversation_id,))
            row = cursor.fetchone()
            if not row:
                raise RuntimeError("conversation not found")
            if row.get("parentid") is not None:
                raise RuntimeError("child conversation cannot be reordered")
    row_list = _get_present_conversation_rank_rows(db)
    conversation_id_text = str(conversation_id)
    row_by_id = _get_ranked_conversation_by_id(row_list)
    if conversation_id_text not in row_by_id:
        raise RuntimeError("conversation not found or is in trashbin")

    id_list = [item["id"] for item in row_list if item["id"] != conversation_id_text]
    before_id = _to_text(conversation_id_before)
    after_id = _to_text(conversation_id_after)
    if before_id == conversation_id_text:
        before_id = ""
    if after_id == conversation_id_text:
        after_id = ""
    if before_id and before_id not in id_list:
        before_id = ""
    if after_id and after_id not in id_list:
        after_id = ""
    if before_id and after_id and id_list.index(before_id) > id_list.index(after_id):
        before_id = ""

    if after_id:
        index_next = id_list.index(after_id)
    elif before_id:
        index_next = id_list.index(before_id) + 1
    else:
        index_next = len(id_list)
    id_list.insert(index_next, conversation_id_text)

    rank_by_id = _get_ranked_conversation_by_id(row_list)
    rank_before_id = id_list[index_next - 1] if index_next > 0 else ""
    rank_after_id = id_list[index_next + 1] if index_next + 1 < len(id_list) else ""
    rank_before = _get_valid_neighbor_rank(rank_by_id, rank_before_id)
    rank_after = _get_valid_neighbor_rank(rank_by_id, rank_after_id)
    is_neighbor_rank_missing = (rank_before_id and not rank_before) or (rank_after_id and not rank_after)
    rank_next = "" if is_neighbor_rank_missing else get_rank_between(rank_before, rank_after)
    if not rank_next:
        rank_by_id_next = _rebalance_present_conversation_ranks(db, id_list)
        rank_next = rank_by_id_next[conversation_id_text]

    if not is_lexorank_valid(rank_next):
        raise RuntimeError("could not create rank")

    with closing(db.cursor()) as cursor:
        cursor.execute(
            """
            update conversation
            set rankGlobal = %s,
                updateAt = now(),
                updateAtTimezone = %s
            where id = %s
            """,
            (rank_next, timezone, conversation_id),
        )
    return get_conversation_by_id(db, conversation_id)


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
        parent_id = _normalize_parent_id(body.get("parentId"))

        def action(db):
            return create_conversation_in_db(db, normalize_conversation_metadata_for_create(body.get("metadata")), timezone, parent_id)

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
        parent_id_filter = _to_text(body.get("parentId") if request.method == "POST" else request.args.get("parentId"))
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
            where_part_list = []
            params = []
            if search_text:
                where_part_list.append("metadata::text ilike %s")
                params.append(f"%{search_text}%")
            has_parent_id_column = _has_conversation_parent_id_column(db)
            if has_parent_id_column:
                if parent_id_filter == "*":
                    pass
                elif parent_id_filter:
                    where_part_list.append("parentId = %s")
                    params.append(int(parent_id_filter))
                else:
                    where_part_list.append("parentId is null")
            where_clause = f"where {' and '.join(where_part_list)}" if where_part_list else ""
            if _has_conversation_rank_global_column(db) and has_parent_id_column:
                order_clause = """
                    order by
                      case when parentId is null then 0 else 1 end asc,
                      isInTrashbin asc,
                      case when rankGlobal ~ '^[0-9A-Za-z]{12}$' then 0 else 1 end asc,
                      rankGlobal collate "C" asc nulls last,
                      updateAt desc,
                      id desc
                """
            elif _has_conversation_rank_global_column(db):
                order_clause = """
                    order by
                      isInTrashbin asc,
                      case when rankGlobal ~ '^[0-9A-Za-z]{12}$' then 0 else 1 end asc,
                      rankGlobal collate "C" asc nulls last,
                      updateAt desc,
                      id desc
                """
            else:
                order_clause = "order by updateAt desc, id desc"
            with closing(dict_cursor(db)) as cursor:
                cursor.execute(f"select count(1) as totalCount from conversation {where_clause}", tuple(params))
                total_row = cursor.fetchone()
                total_count = int(total_row["totalcount"] if total_row else 0)
                cursor.execute(
                    f"""
                    select {_get_conversation_select_sql(db)}
                    from conversation
                    {where_clause}
                    {order_clause}
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
                cursor.execute("select metadata, parentId from conversation where id = %s for update", (int(conversation_id),))
                row = cursor.fetchone()
                if not row:
                    raise RuntimeError("conversation not found")
                if row.get("parentid") is not None:
                    raise RuntimeError("child conversation cannot be renamed")
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
            with closing(dict_cursor(db)) as cursor:
                if _has_conversation_parent_id_column(db):
                    cursor.execute("select parentId from conversation where id = %s for update", (int(conversation_id),))
                    row = cursor.fetchone()
                    if not row:
                        raise RuntimeError("conversation not found")
                    if row.get("parentid") is not None:
                        raise RuntimeError("child conversation cannot be moved to trashbin directly")
                    cursor.execute(
                        """
                        with recursive descendant(id) as (
                            select id
                            from conversation
                            where id = %s
                            union all
                            select child.id
                            from conversation child
                            join descendant on child.parentId = descendant.id
                        )
                        update conversation
                        set isInTrashbin = %s,
                            updateAt = now(),
                            updateAtTimezone = %s
                        where id in (select id from descendant)
                        """,
                        (int(conversation_id), is_in_trashbin, timezone),
                    )
                else:
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

    @app.post("/api/conversation/reorder")
    def conversation_reorder():
        if not has_request_permission("W"):
            return make_json_response(-1, message="write permission required"), 403
        body = request.get_json(silent=True) or {}
        conversation_id = _to_text(body.get("conversationId"))
        if not conversation_id:
            return make_json_response(-10, message="conversationId is required"), 400
        timezone = _normalize_timezone(body.get("timezone"))

        def action(db):
            return reorder_present_conversation_in_db(
                db,
                int(conversation_id),
                _to_text(body.get("conversationIdBefore")),
                _to_text(body.get("conversationIdAfter")),
                timezone,
            )

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
                metadata_next["eventList"] = metadata_existing["eventList"]
                metadata_next["childConversationIdList"] = metadata_existing["childConversationIdList"]
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
                cursor.execute("select id, parentId from conversation where id = %s for update", (int(conversation_id),))
                row = cursor.fetchone()
                if not row:
                    raise RuntimeError("conversation not found")
                if row.get("parentid") is not None:
                    raise RuntimeError("child conversation cannot be deleted directly")
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
