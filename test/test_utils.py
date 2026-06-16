import json
import sys
from datetime import datetime
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
ROOT_DIR = TEST_DIR.parent
if str(ROOT_DIR) not in sys.path:
  sys.path.insert(0, str(ROOT_DIR))
from backend_api_log import print_backend_log_result, try_log_messages_to_backend


def build_time_stamp(time_value=None):
  time_local = time_value or datetime.now().astimezone()
  milli_10 = time_local.microsecond // 10000
  offset = time_local.utcoffset()
  offset_hours = int(offset.total_seconds() // 3600) if offset else 0
  offset_sign = "+" if offset_hours >= 0 else "-"
  offset_value = f"{abs(offset_hours):02d}"
  return f"{time_local:%Y%m%d_%H%M%S}{milli_10:02d}{offset_sign}{offset_value}"


def append_message(messages, role, text, event_type=None, event_subtype=None):
  messages.append({
    "role": role,
    "text": text,
    "eventType": event_type or "",
    "eventSubtype": event_subtype or "",
  })


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


def try_write_backend_conversation_log(messages, final_status, title, source_text):
  result = try_log_messages_to_backend(
    messages,
    metadata={
      "title": title,
      "statusText": final_status,
      "sourceText": source_text,
    },
  )
  print_backend_log_result(result)
  return result
