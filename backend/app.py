from __future__ import annotations

import os
from typing import Any

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_sock import Sock

from config import DEFAULT_PORT, get_dir_base, load_content_type_config
from conversation import register_conversation_routes
from db import database_config, ensure_database_exists, ensure_schema_exists, reinit_database
from event import register_event_routes
from iteration_executor import register_orchestrator_routes
from iteration_scheduler import ensure_conversation_iter_schema, start_conversation_iter_runtime
from login import has_request_permission, is_request_authorized, register_login_routes
from update_ws import register_update_ws_routes


def make_json_response(code: int, data: Any = None, message: str = ""):
    response_data = {"code": code}
    if data is not None:
        response_data["data"] = data
    if message:
        response_data["message"] = message
    return jsonify(response_data)


app = Flask(__name__)
sock = Sock(app)
APP_BASE_ASSET_PLACEHOLDER = "/__APP_BASE__/"
APP_PUBLIC_PREFIXES = ("/agent-flow",)
is_database_bootstrap_ok = False
database_bootstrap_error_text = ""


class PublicPrefixMiddleware:
    def __init__(self, app_wsgi):
        self.app_wsgi = app_wsgi

    def __call__(self, environ, start_response):
        path_info = str(environ.get("PATH_INFO") or "")
        for prefix in APP_PUBLIC_PREFIXES:
            if path_info == prefix:
                environ["PATH_INFO"] = "/"
                environ.setdefault("HTTP_X_FORWARDED_PREFIX", prefix)
                break
            if path_info.startswith(f"{prefix}/"):
                environ["PATH_INFO"] = path_info[len(prefix):] or "/"
                environ.setdefault("HTTP_X_FORWARDED_PREFIX", prefix)
                break
        return self.app_wsgi(environ, start_response)


app.wsgi_app = PublicPrefixMiddleware(app.wsgi_app)


def get_build_dir():
    return get_dir_base() / "frontend" / "dist"


def get_frontend_asset_base():
    forwarded_prefix = str(request.headers.get("X-Forwarded-Prefix") or "").strip()
    if forwarded_prefix:
        return f"/{forwarded_prefix.strip('/')}/"
    return "/"


def is_static_asset_path(path: str):
    path_text = str(path or "").strip("/")
    return path_text.startswith("assets/") or "." in path_text.rsplit("/", 1)[-1]


def serve_frontend_page():
    build_dir = get_build_dir()
    index_file = build_dir / "index.html"
    if index_file.is_file():
        index_html = index_file.read_text(encoding="utf-8")
        index_html = index_html.replace(APP_BASE_ASSET_PLACEHOLDER, get_frontend_asset_base())
        return Response(index_html, mimetype="text/html")
    return make_json_response(-1, message=f"build not found: {build_dir}"), 404


@app.before_request
def auth_guard():
    path = str(request.path or "")
    public_paths = {
        "/api/health/ping",
        "/login",
        "/login/token",
    }
    if path in public_paths:
        return None
    if path.startswith("/api/") or path == "/login/check":
        if is_request_authorized():
            return None
        return make_json_response(-1, message="unauthorized"), 401
    return None


@app.get("/api/health/ping")
def health_ping():
    return make_json_response(
        0,
        data={
            "status": "running",
            "service": "react-agent-flow",
            "isDatabaseBootstrapOk": is_database_bootstrap_ok,
            "databaseBootstrapErrorText": database_bootstrap_error_text,
        },
    )


@app.get("/api/health/database")
def health_database():
    if not has_request_permission("R"):
        return make_json_response(-1, message="read permission required"), 403
    return make_json_response(
        0,
        data={
            "databaseKey": database_config["key"],
            "databaseName": database_config["databaseName"],
            "host": database_config["host"],
            "port": database_config["port"],
            "username": database_config["username"],
            "isDatabaseBootstrapOk": is_database_bootstrap_ok,
            "databaseBootstrapErrorText": database_bootstrap_error_text,
        },
    )


@app.get("/api/config/content-type/list")
def config_content_type_list():
    if not has_request_permission("R"):
        return make_json_response(-1, message="read permission required"), 403
    config = load_content_type_config()
    content_type_by_code = config.get("contentTypeByCode") if isinstance(config, dict) else {}
    item_list = []
    for code_text, item in sorted(content_type_by_code.items(), key=lambda entry: int(entry[0])):
        if not isinstance(item, dict):
            continue
        item_list.append(
            {
                "contentType": int(code_text),
                "name": str(item.get("name") or ""),
                "activeColumn": str(item.get("activeColumn") or ""),
            }
        )
    return make_json_response(0, data={"items": item_list})


@app.post("/api/service/database/reinit")
def service_database_reinit():
    if not has_request_permission("W"):
        return make_json_response(-1, message="write permission required"), 403
    try:
        return make_json_response(0, data=reinit_database())
    except Exception as error:
        return make_json_response(-1, message=str(error)), 500


register_login_routes(app, make_json_response)
register_conversation_routes(app, make_json_response)
register_event_routes(app, make_json_response)
register_orchestrator_routes(app, make_json_response)
register_update_ws_routes(sock)


@app.errorhandler(404)
def handle_not_found(_error):
    if request.method == "GET" and not str(request.path or "").startswith("/api/"):
        if is_static_asset_path(request.path):
            return make_json_response(-1, message=f"static asset not found: {request.path}"), 404
        return serve_frontend_page()
    return make_json_response(-1, message=f"endpoint not found: {request.path}"), 404


@app.errorhandler(405)
def handle_method_not_allowed(_error):
    return make_json_response(-1, message=f"method not allowed: {request.path}"), 405


@app.get("/", defaults={"resource_path": ""})
@app.get("/<path:resource_path>")
def serve_frontend(resource_path: str):
    build_dir = get_build_dir()
    if resource_path:
        file_path = build_dir / resource_path
        if file_path.is_file():
            return send_from_directory(build_dir, resource_path)
        if is_static_asset_path(resource_path):
            return make_json_response(-1, message=f"static asset not found: /{resource_path}"), 404
    return serve_frontend_page()


def bootstrap_app():
    global is_database_bootstrap_ok
    global database_bootstrap_error_text
    try:
        ensure_database_exists()
        ensure_schema_exists()
        ensure_conversation_iter_schema()
        start_conversation_iter_runtime()
        is_database_bootstrap_ok = True
        database_bootstrap_error_text = ""
    except Exception as error:
        is_database_bootstrap_ok = False
        database_bootstrap_error_text = str(error)


if __name__ == "__main__":
    bootstrap_app()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", str(DEFAULT_PORT))))
