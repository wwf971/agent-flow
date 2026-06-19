from __future__ import annotations

import json


TEMPLATE_KEY = "subagent-test"


def orchestrator_iter(context):
  event_list = context.get("eventList") if isinstance(context.get("eventList"), list) else []
  event_latest = event_list[-1] if event_list else {}
  if event_latest.get("subtypeText") == "subAgentResult":
    yield build_agent_summary_event(event_latest)
    return
  if has_subagent_request(event_list):
    yield build_followup_answer_event(context, event_list)
    return
  message_text = str(context.get("messageText") or "").strip()
  if not message_text:
    message_text = "Return a short greeting to the parent."
  yield build_subagent_tool_call_event(message_text)


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


def build_followup_answer_event(context, event_list):
  result_event = get_latest_subagent_result_event(event_list)
  if not result_event:
    answer_text = "I have already launched the subagent and am waiting for its result."
  else:
    data = extract_subagent_result_data(result_event)
    subagent_list = data.get("subagents") if isinstance(data.get("subagents"), list) else []
    total_count = len(subagent_list)
    success_count = sum(1 for item in subagent_list if isinstance(item, dict) and item.get("isReturned") is True)
    answer_text = (
      f"I launched {total_count} subagent"
      f"{'' if total_count == 1 else 's'}. "
      f"{success_count} returned successfully."
    )
    message_text = str(context.get("messageText") or "").strip()
    if message_text:
      answer_text = f"{answer_text}\n\nYour question: {message_text}"
  return {
    "typeText": "agentMessage",
    "subtypeText": "textSimple",
    "contentType": 1,
    "contentText": answer_text,
    "metadata": {"templateKey": TEMPLATE_KEY},
  }


def get_latest_subagent_result_event(event_list):
  for event in reversed(event_list):
    if event.get("subtypeText") == "subAgentResult":
      return event
  return None
