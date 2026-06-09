from __future__ import annotations

import secrets
from typing import Any

from flask import make_response, request

from config import get_dir_base, get_project_config

AUTH_COOKIE_NAME = "react_agent_flow_auth"
AUTH_TOKEN_STORE_FILE = get_dir_base() / ".runtime" / "auth_tokens.txt"
DEFAULT_PERMISSION = "R"


def _to_text(value: Any):
    return str(value or "").strip()


def _normalize_permission(value: Any):
    raw_text = _to_text(value).upper()
    permission_text = "".join([char for char in raw_text if char in ("R", "W")])
    return permission_text or DEFAULT_PERMISSION


def _normalize_auth_user(raw_user: Any, fallback_username: str = ""):
    if not isinstance(raw_user, dict):
        return None
    username = _to_text(raw_user.get("username")) or _to_text(fallback_username)
    password = str(raw_user.get("password") or "")
    if not username or not password:
        return None
    return {
        "username": username,
        "password": password,
        "permission": _normalize_permission(raw_user.get("permission")),
    }


def _load_auth_users():
    project_config = get_project_config()
    auth_config = project_config.get("auth")
    user_list = []
    if isinstance(auth_config, dict):
        raw_users = auth_config.get("users")
        if isinstance(raw_users, list):
            for raw_user in raw_users:
                user = _normalize_auth_user(raw_user)
                if user:
                    user_list.append(user)
        if not user_list:
            user = _normalize_auth_user(
                {
                    "username": auth_config.get("login_username"),
                    "password": auth_config.get("login_password"),
                    "permission": auth_config.get("permission", "RW"),
                },
                "example",
            )
            if user:
                user_list.append(user)
    if not user_list:
        user_list.append({"username": "example", "password": "12345678", "permission": "RW"})
    return user_list


AUTH_USERS = _load_auth_users()
_auth_user_by_username = {user["username"]: user for user in AUTH_USERS}
_auth_token_user_by_token: dict[str, str] = {}


def _load_persisted_tokens():
    if not AUTH_TOKEN_STORE_FILE.is_file():
        return
    try:
        for line in AUTH_TOKEN_STORE_FILE.read_text(encoding="utf-8").splitlines():
            line_text = _to_text(line)
            if not line_text or "\t" not in line_text:
                continue
            token, username = line_text.split("\t", 1)
            if token and username in _auth_user_by_username:
                _auth_token_user_by_token[token] = username
    except OSError:
        return


def _persist_token(token: str, username: str):
    normalized_token = _to_text(token)
    normalized_username = _to_text(username)
    if not normalized_token or not normalized_username:
        return
    try:
        AUTH_TOKEN_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        token_map = {}
        if AUTH_TOKEN_STORE_FILE.is_file():
            for line in AUTH_TOKEN_STORE_FILE.read_text(encoding="utf-8").splitlines():
                line_text = _to_text(line)
                if not line_text or "\t" not in line_text:
                    continue
                token_text, username_text = line_text.split("\t", 1)
                if token_text and username_text in _auth_user_by_username:
                    token_map[token_text] = username_text
        token_map[normalized_token] = normalized_username
        AUTH_TOKEN_STORE_FILE.write_text(
            "\n".join([f"{item_token}\t{item_user}" for item_token, item_user in sorted(token_map.items())]) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return


_load_persisted_tokens()


def issue_auth_token(username: str):
    token = secrets.token_urlsafe(24)
    _auth_token_user_by_token[token] = username
    _persist_token(token, username)
    return token


def validate_auth_token(token: str):
    normalized_token = _to_text(token)
    return bool(normalized_token and normalized_token in _auth_token_user_by_token)


def get_user_by_token(token: str):
    username = _auth_token_user_by_token.get(_to_text(token))
    if not username:
        return None
    return _auth_user_by_username.get(username)


def extract_request_auth_token():
    auth_header = _to_text(request.headers.get("Authorization"))
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    token_from_header = _to_text(request.headers.get("X-Auth-Token"))
    if token_from_header:
        return token_from_header
    token_from_query = _to_text(request.args.get("authToken"))
    if token_from_query:
        return token_from_query
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        if isinstance(body, dict):
            token_from_body = _to_text(body.get("authToken"))
            if token_from_body:
                return token_from_body
    return _to_text(request.cookies.get(AUTH_COOKIE_NAME))


def get_request_user():
    return get_user_by_token(extract_request_auth_token())


def is_request_authorized():
    return validate_auth_token(extract_request_auth_token())


def get_request_permission():
    user = get_request_user()
    return _normalize_permission(user.get("permission") if user else "")


def has_request_permission(permission_char: str):
    return _to_text(permission_char).upper() in get_request_permission()


def _is_secure_request():
    forwarded_proto = _to_text(request.headers.get("X-Forwarded-Proto")).lower()
    if forwarded_proto:
        return forwarded_proto == "https"
    return request.is_secure


def attach_auth_token_cookie(response, token: str):
    resp = make_response(response)
    resp.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        httponly=True,
        samesite="Lax",
        secure=_is_secure_request(),
        path="/",
        max_age=60 * 60 * 24 * 30,
    )
    return resp


def register_login_routes(app, make_json_response):
    @app.post("/login")
    def login_with_credentials():
        body = request.get_json(silent=True) or {}
        username = _to_text(body.get("username"))
        password = str(body.get("password") or "")
        user = _auth_user_by_username.get(username)
        if not user or password != user["password"]:
            return make_json_response(-1, message="invalid username or password"), 401
        token = issue_auth_token(username)
        return attach_auth_token_cookie(
            make_json_response(0, data={"token": token, "username": username, "permission": user["permission"]}),
            token,
        )

    @app.post("/login/token")
    def login_with_token():
        body = request.get_json(silent=True) or {}
        token = _to_text(body.get("token"))
        user = get_user_by_token(token)
        if not user:
            return make_json_response(-1, message="invalid token"), 401
        return attach_auth_token_cookie(
            make_json_response(0, data={"token": token, "username": user["username"], "permission": user["permission"]}),
            token,
        )

    @app.get("/login/check")
    def login_check():
        user = get_request_user()
        if not user:
            return make_json_response(-1, message="unauthorized"), 401
        return make_json_response(
            0,
            data={"isLoggedIn": True, "username": user["username"], "permission": user["permission"]},
        )
