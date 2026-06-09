import json
import os
import sys
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types

THIS_DIR = Path(__file__).resolve().parent
ROOT_DIR = THIS_DIR.parents[1]
if str(ROOT_DIR) not in sys.path:
  sys.path.insert(0, str(ROOT_DIR))
from backend_api_log import print_backend_log_result, try_log_messages_to_backend

CONFIG_PATHS = [
  ROOT_DIR / "config" / "config.0.yaml",
  ROOT_DIR / "config" / "config.yaml",
  ROOT_DIR / "config.yaml",
]


def build_time_stamp(time_value=None):
  time_local = time_value or datetime.now().astimezone()
  milli_10 = time_local.microsecond // 10000
  offset = time_local.utcoffset()
  offset_hours = int(offset.total_seconds() // 3600) if offset else 0
  offset_sign = "+" if offset_hours >= 0 else "-"
  offset_value = f"{abs(offset_hours):02d}"
  return f"{time_local:%Y%m%d_%H%M%S}{milli_10:02d}{offset_sign}{offset_value}"


def load_config_value(config_key):
  for config_path in CONFIG_PATHS:
    if not config_path.exists():
      continue
    with open(config_path, "r", encoding="utf-8") as config_file:
      for raw_line in config_file:
        line = raw_line.strip()
        if not line or line.startswith("#"):
          continue
        if not line.startswith(f"{config_key}:"):
          continue
        value = line.split(":", 1)[1].strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
          value = value[1:-1]
        return value
  return ""


def build_client_and_model():
  api_key = load_config_value("google_api_key") or os.getenv("GOOGLE_API_KEY")
  model_name = load_config_value("google_model") or "gemini-2.5-flash"
  if not api_key:
    raise ValueError(
      "Please set google_api_key in config/config.yaml or GOOGLE_API_KEY in your environment."
    )
  return genai.Client(api_key=api_key), model_name


def append_message(messages, role, text, event_type=None, event_subtype=None):
  messages.append({
    "role": role,
    "text": text,
    "eventType": event_type or "",
    "eventSubtype": event_subtype or "",
  })


def build_agent_input(messages):
  lines = []
  for message in messages:
    role = message["role"]
    text = message["text"]
    lines.append(f"{role.upper()}:\n{text}")
  return "\n\n".join(lines)


def ask_agent(client, model_name, messages):
  response = client.models.generate_content(
    model=model_name,
    contents=build_agent_input(messages),
    config=types.GenerateContentConfig(
      temperature=0.0,
    ),
  )
  return (response.text or "").strip()


def shorten_text(text, limit=800):
  if len(text) <= limit:
    return text
  return f"{text[:limit]}..."


def format_tool_result_for_print(result):
  result_copy = dict(result)
  if isinstance(result_copy.get("text"), str):
    result_copy["text"] = shorten_text(result_copy["text"], limit=500)
  return json.dumps(result_copy, ensure_ascii=False, indent=2)


def print_section(title, text):
  print("")
  print(f"===== {title} =====")
  print(text)


def write_conversation_log(log_path, messages, final_status):
  lines = [f"final_status: {final_status}", ""]
  for index, message in enumerate(messages, start=1):
    lines.append(f"===== {index}. {message['role'].upper()} =====")
    lines.append(message["text"])
    lines.append("")
  with open(log_path, "w", encoding="utf-8") as log_file:
    log_file.write("\n".join(lines))


def try_write_backend_conversation_log(messages, final_status, title):
  result = try_log_messages_to_backend(
    messages,
    metadata={
      "title": title,
      "statusText": final_status,
      "sourceText": "_1_mcp",
    },
  )
  print_backend_log_result(result)
  return result
