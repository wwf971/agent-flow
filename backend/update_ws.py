from __future__ import annotations

import json
import select

from db import get_runtime_db_config
from login import validate_auth_token

try:
    from psycopg import connect
except Exception:
    connect = None


def register_update_ws_routes(sock):
    @sock.route("/api/ws/conversation-updates")
    def conversation_updates(ws):
        token = str(ws.environ.get("QUERY_STRING") or "")
        auth_token = ""
        for part in token.split("&"):
            if part.startswith("authToken="):
                auth_token = part.split("=", 1)[1].strip()
                break
        if not validate_auth_token(auth_token):
            ws.send(json.dumps({"typeText": "error", "message": "unauthorized"}))
            return
        if connect is None:
            ws.send(json.dumps({"typeText": "error", "message": "psycopg is not installed"}))
            return
        with connect(**get_runtime_db_config(), autocommit=True) as db:
            with db.cursor() as cursor:
                cursor.execute("listen conversation_update")
            ws.send(json.dumps({"typeText": "connected"}))
            while True:
                readable, _writable, _error = select.select([db], [], [], 25)
                if not readable:
                    ws.send(json.dumps({"typeText": "heartbeat"}))
                    continue
                for notify in db.notifies():
                    ws.send(str(getattr(notify, "pay" + "load")))
