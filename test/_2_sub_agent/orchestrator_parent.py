from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
TEST_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
  sys.path.insert(0, str(ROOT_DIR))
if str(TEST_DIR) not in sys.path:
  sys.path.insert(0, str(TEST_DIR))

from api_llm import ask_agent
from backend.config import get_model_service_config
from test_utils import prompt_text_tool_call_pure_json, tool_call_agent_reply_parse

TEMPLATE_KEY = "subagent-test"
DEFAULT_PARENT_REQUEST = "Ask one child subagent to return a short hello text to the parent."


def orchestrator_iter(context):
  event_list = context.get("eventList") if isinstance(context.get("eventList"), list) else []
  event_latest = event_list[-1] if event_list else {}
  if event_latest.get("subtypeText") == "subAgentResult":
    yield build_agent_summary_event(event_latest)
    return
  if has_subagent_request(event_list):
    yield from iter_followup_user_turn(context, event_list)
    return
  message_text = str(context.get("messageText") or "").strip()
  if not message_text:
    message_text = DEFAULT_PARENT_REQUEST
  yield build_parent_instruction_event(message_text)
  yield build_subagent_tool_call_event(message_text)


def message_list_from_events(event_list):
  messages = []
  for event in event_list:
    type_text = str(event.get("typeText") or "")
    subtype_text = str(event.get("subtypeText") or "")
    content_text = str(event.get("contentText") or "")
    if subtype_text != "textSimple" or not content_text:
      continue
    if type_text == "agentMessage":
      role = "assistant"
    else:
      role = "user"
    messages.append({"role": role, "text": content_text})
  return messages


def build_followup_system_prompt(backend_tool_list):
  tool_lines = []
  for tool in backend_tool_list:
    if not isinstance(tool, dict):
      continue
    tool_lines.append(f"- {tool.get('name')}: {tool.get('description')}")
  tool_block = "\n".join(tool_lines) if tool_lines else "- tool_subagent: launch child subagents"
  return f"""
You are the parent agent in an interactive subagent test conversation.

You can reply in natural language when no tool is needed.
When the user asks to launch another subagent, reply with only JSON in this shape:
{{
  "action": "tool_call",
  "tool_name": "tool_subagent",
  "args": {{
    "maxTurns": 4,
    "subagents": [
      {{
        "name": "text child",
        "initialPrompt": "short task for the child"
      }}
    ]
  }}
}}

{prompt_text_tool_call_pure_json()}

Available tools:
{tool_block}
- tool_terminate_conversation: end the conversation when the user clearly says goodbye.

If the user says bye, goodbye, or similar, call tool_terminate_conversation.
""".strip()


def parse_tool_call(reply_text, backend_tool_list):
  tool_name_list = [str(tool.get("name") or "") for tool in backend_tool_list if isinstance(tool, dict)]
  tool_name_list.append("tool_terminate_conversation")
  tool_call, _error_text = tool_call_agent_reply_parse(
    reply_text,
    tool_name_list,
    is_allow_repeated_tool=True,
  )
  return tool_call


def iter_followup_user_turn(context, event_list):
  backend_tool_list = context.get("backendToolList") if isinstance(context.get("backendToolList"), list) else []
  messages = message_list_from_events(event_list)
  messages.insert(0, {"role": "user", "text": build_followup_system_prompt(backend_tool_list)})
  model_config = get_model_service_config()
  reply_agent = ask_agent(model_config, messages)
  tool_call = parse_tool_call(reply_agent, backend_tool_list)
  if tool_call is None:
    yield {
      "typeText": "agentMessage",
      "subtypeText": "textSimple",
      "contentType": 1,
      "contentText": reply_agent,
      "metadata": {"templateKey": TEMPLATE_KEY},
    }
    return
  tool_name = tool_call["tool_name"]
  yield {
    "typeText": "agentMessage",
    "subtypeText": "toolCall",
    "contentType": 3,
    "contentText": reply_agent,
    "contentJson": tool_call,
    "metadata": {"templateKey": TEMPLATE_KEY, "toolName": tool_name},
  }
  if tool_name == "tool_subagent":
    return
  reason_text = str(tool_call["args"].get("reason") or "The user ended the conversation.")
  result = {
    "status": "success",
    "is_terminated": True,
    "reason": reason_text,
  }
  reply_orchestrator = f"Tool result: {json.dumps(result, ensure_ascii=False)}"
  yield {
    "typeText": "orchestratorMessage",
    "subtypeText": "toolResult",
    "contentType": 3,
    "contentText": reply_orchestrator,
    "contentJson": {
      "metadata": {
        "schemaVersion": 1,
        "kind": "toolResult",
        "toolName": tool_name,
      },
      "data": [
        {"type": "text", "data": "Tool result: "},
        {"type": "json", "data": result},
      ],
    },
    "metadata": {"templateKey": TEMPLATE_KEY, "toolName": tool_name},
  }


def build_parent_instruction_event(message_text):
  content_text = (
    "You are the parent agent for the Subagent Test template.\n\n"
    "Available backend tool:\n"
    "- tool_subagent: launch one or more child subagent conversations. Each child receives an initialPrompt and must return through tool_return_to_parent.\n\n"
    "For this test, launch exactly one child subagent and ask it to return a short hello text to the parent.\n\n"
    f"Parent request: {message_text}"
  )
  return {
    "typeText": "orchestratorMessage",
    "subtypeText": "textSimple",
    "contentType": 1,
    "contentText": content_text,
    "metadata": {"templateKey": TEMPLATE_KEY, "isInitialPrompt": True},
  }


def build_subagent_tool_call_event(message_text):
  tool_call = {
    "action": "tool_call",
    "tool_name": "tool_subagent",
    "args": {
      "maxTurns": 4,
      "subagents": [
        {
          "name": "text child",
          "initialPrompt": (
            "Answer the parent request with short plain text. "
            "When ready, call tool_return_to_parent with args.returnValue as the answer text. "
            f"Parent request: {message_text}"
          ),
        },
      ],
    },
  }
  return {
    "typeText": "agentMessage",
    "subtypeText": "toolCall",
    "contentType": 3,
    "contentText": json.dumps(tool_call, ensure_ascii=False),
    "contentJson": tool_call,
    "metadata": {"templateKey": TEMPLATE_KEY, "toolName": "tool_subagent"},
  }


def build_agent_summary_event(event_subagent_result):
  data = extract_subagent_result_data(event_subagent_result)
  subagent_list = data.get("subagents") if isinstance(data.get("subagents"), list) else []
  line_list = ["Subagent result:"]
  for item_raw in subagent_list:
    item = item_raw if isinstance(item_raw, dict) else {}
    name_text = str(item.get("name") or item.get("conversationId") or "subagent")
    status_text = str(item.get("statusText") or "")
    return_value = item.get("returnValue")
    failure_reason = str(item.get("failureReason") or "")
    if failure_reason:
      line_list.append(f"- {name_text}: {status_text}, {failure_reason}")
    else:
      line_list.append(f"- {name_text}: {status_text}, {return_value}")
  return {
    "typeText": "agentMessage",
    "subtypeText": "textSimple",
    "contentType": 1,
    "contentText": "\n".join(line_list),
    "metadata": {"templateKey": TEMPLATE_KEY},
  }


def extract_subagent_result_data(event_subagent_result):
  content_json = event_subagent_result.get("contentJson")
  if not isinstance(content_json, dict):
    return {}
  data_list = content_json.get("data")
  if not isinstance(data_list, list):
    return {}
  for item_raw in data_list:
    item = item_raw if isinstance(item_raw, dict) else {}
    if item.get("type") == "json" and isinstance(item.get("data"), dict):
      return item["data"]
  return {}


def has_subagent_request(event_list):
  for event in event_list:
    content_json = event.get("contentJson") if isinstance(event.get("contentJson"), dict) else {}
    if event.get("subtypeText") == "toolCall" and content_json.get("tool_name") == "tool_subagent":
      return True
  return False
