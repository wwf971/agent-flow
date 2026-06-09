from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

try:
  import requests
except Exception:
  requests = None

try:
  import yaml
except Exception:
  yaml = None

ROOT_DIR = Path(__file__).resolve().parent
LOCAL_TEST_CONFIG_PATH = ROOT_DIR / "config" / "config-local-test.yaml"


def _to_text(value: Any):
  return str(value or "").strip()


def _load_local_test_config():
  if yaml is None:
    raise RuntimeError("PyYAML is not installed")
  if not LOCAL_TEST_CONFIG_PATH.is_file():
    return {}
  with LOCAL_TEST_CONFIG_PATH.open("r", encoding="utf-8") as file:
    data = yaml.safe_load(file) or {}
  if not isinstance(data, dict):
    return {}
  return data


def _normalize_backend_url(value: Any):
  url = _to_text(value).rstrip("/")
  if not url:
    return ""
  if url.startswith("http://") or url.startswith("https://"):
    return url
  return f"http://{url}"


def _get_timezone_minutes():
  time_current = datetime.now().astimezone()
  offset = time_current.utcoffset()
  if offset is None:
    return 0
  return int(offset.total_seconds() // 60)


def _post_json(url: str, data: dict[str, Any], token: str = ""):
  if requests is None:
    raise RuntimeError("requests is not installed")
  headers = {}
  if token:
    headers["Authorization"] = f"Bearer {token}"
  response = requests.post(url, json=data, headers=headers, timeout=5)
  response.raise_for_status()
  response_data = response.json()
  if int(response_data.get("code", -1)) < 0:
    raise RuntimeError(_to_text(response_data.get("message")) or f"backend returned code {response_data.get('code')}")
  return response_data.get("data") or {}


def _login(backend_url: str, username: str, password: str):
  data = _post_json(
    f"{backend_url}/login",
    {
      "username": username,
      "password": password,
    },
  )
  return _to_text(data.get("token"))


def _create_conversation(backend_url: str, token: str, metadata: dict[str, Any], timezone: int):
  data = _post_json(
    f"{backend_url}/api/conversation/create",
    {
      "metadata": metadata,
      "timezone": timezone,
    },
    token,
  )
  return _to_text(data.get("conversationId"))


def _create_event(
  backend_url: str,
  token: str,
  conversation_id: str,
  type_text: str,
  subtype_text: str,
  content_text: str,
  metadata: dict[str, Any],
  timezone: int,
):
  return _post_json(
    f"{backend_url}/api/event/create",
    {
      "conversationId": conversation_id,
      "typeText": type_text,
      "subtypeText": subtype_text,
      "contentType": 1,
      "contentText": content_text,
      "metadata": metadata,
      "timezone": timezone,
    },
    token,
  )


def _message_type_from_role(message: dict[str, Any]):
  type_text = _to_text(message.get("eventType"))
  if type_text:
    return type_text
  role = _to_text(message.get("role")).lower()
  if role == "assistant":
    return "agentMessage"
  if role == "orchestrator":
    return "orchestratorMessage"
  return "userMessage"


def try_log_messages_to_backend(messages: list[dict[str, Any]], metadata: dict[str, Any] | None = None):
  try:
    config = _load_local_test_config()
    backend_url = _normalize_backend_url(config.get("backend_url"))
    username = _to_text(config.get("username"))
    password = str(config.get("password") or "")
    if not backend_url or not username or not password:
      return {"isLogged": False, "warning": "backend logging config is incomplete"}
    timezone = _get_timezone_minutes()
    token = _login(backend_url, username, password)
    conversation_id = _create_conversation(
      backend_url,
      token,
      {
        **(metadata or {}),
        "sourceText": "local-test",
      },
      timezone,
    )
    event_count = 0
    for index, message in enumerate(messages, start=1):
      text = _to_text(message.get("text"))
      if not text:
        continue
      _create_event(
        backend_url,
        token,
        conversation_id,
        _message_type_from_role(message),
        _to_text(message.get("eventSubtype")) or "textSimple",
        text,
        {
          "roleText": _to_text(message.get("role")),
          "index": index,
        },
        timezone,
      )
      event_count = event_count + 1
    return {
      "isLogged": True,
      "backendUrl": backend_url,
      "conversationId": conversation_id,
      "eventCount": event_count,
    }
  except Exception as error:
    return {"isLogged": False, "warning": str(error)}


def try_log_dialogue_to_backend(dialogue: list[tuple[str, str]], metadata: dict[str, Any] | None = None):
  messages = []
  for user_text, agent_text in dialogue:
    messages.append({"role": "user", "eventType": "userMessage", "text": user_text})
    messages.append({"role": "assistant", "eventType": "agentMessage", "text": agent_text})
  return try_log_messages_to_backend(messages, metadata=metadata)


def print_backend_log_result(result: dict[str, Any]):
  if result.get("isLogged"):
    print(f"Backend conversation logged: {result.get('conversationId')}")
    return
  warning = _to_text(result.get("warning"))
  if warning:
    print(f"Backend conversation logging warning: {warning}")
