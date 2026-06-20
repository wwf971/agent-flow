import json
import re
import sys
from datetime import datetime
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
ROOT_DIR = TEST_DIR.parent
if str(ROOT_DIR) not in sys.path:
  sys.path.insert(0, str(ROOT_DIR))
from backend_api_log import print_backend_log_result, try_log_messages_to_backend

ACTION_TOOL_CALL = "tool_call"
FENCE_PATTERN = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL | re.IGNORECASE)


def prompt_text_tool_call_pure_json():
  return (
    "When you call a tool, reply with pure JSON only.\n"
    "Do not wrap JSON in markdown.\n"
    "Do not use ``` or ```json code fences.\n"
    "Do not add text before or after the JSON object."
  )


def json_text_tool_call_normalize(text):
  text_value = str(text or "").strip()
  if not text_value:
    return ""
  fence_match = FENCE_PATTERN.match(text_value)
  if fence_match:
    return str(fence_match.group(1) or "").strip()
  if text_value.startswith("```"):
    line_list = text_value.splitlines()
    if line_list and line_list[0].startswith("```"):
      line_list = line_list[1:]
    if line_list and line_list[-1].strip() == "```":
      line_list = line_list[:-1]
    text_value = "\n".join(line_list).strip()
  return text_value


def json_object_tool_call_load(text):
  text_normalized = json_text_tool_call_normalize(text)
  if not text_normalized:
    return None, "Reply is empty."
  try:
    data = json.loads(text_normalized)
    return data, ""
  except json.JSONDecodeError as error:
    index_start = text_normalized.find("{")
    index_end = text_normalized.rfind("}")
    if index_start >= 0 and index_end > index_start:
      text_fragment = text_normalized[index_start:index_end + 1]
      try:
        data = json.loads(text_fragment)
        return data, ""
      except json.JSONDecodeError:
        pass
    return None, f"JSON parse failed: {error}"


def is_tool_call_action_json(data):
  return isinstance(data, dict) and data.get("action") == ACTION_TOOL_CALL


def tool_call_agent_reply_parse(
  reply_text,
  tool_name_list,
  is_allow_repeated_tool=False,
  tool_name_called_list=None,
):
  data, error_text = json_object_tool_call_load(reply_text)
  if error_text:
    return None, error_text
  if not isinstance(data, dict):
    return None, "Tool call must be a JSON object."
  if data.get("action") != ACTION_TOOL_CALL:
    return None, "The action field must be tool_call."
  tool_name = str(data.get("tool_name") or "").strip()
  tool_name_allowed_list = [str(name or "").strip() for name in (tool_name_list or []) if str(name or "").strip()]
  if tool_name not in tool_name_allowed_list:
    return None, f"Unknown tool_name: {tool_name or '(empty)'}"
  tool_name_called_list_value = tool_name_called_list if isinstance(tool_name_called_list, list) else []
  if not is_allow_repeated_tool and tool_name in tool_name_called_list_value:
    return None, f"The tool {tool_name} was already completed. Choose a remaining tool."
  args = data.get("args")
  if not isinstance(args, dict):
    return None, "The args field must be an object."
  return {
    "tool_name": tool_name,
    "args": args,
  }, ""


def is_tool_call_agent_reply(text):
  data, error_text = json_object_tool_call_load(text)
  if error_text:
    return False
  return is_tool_call_action_json(data)


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
