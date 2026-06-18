from __future__ import annotations

from common import generate_new_turn_with_live_fetch


TEMPLATE_INFO = {
  "key": "web-fetch-local",
  "name": "Web Fetch Local",
  "description": "Fetches live web page text and asks the model to answer from the fetched text.",
}


def _to_dialogue(event_list):
  dialogue = []
  user_text = ""
  for event in event_list:
    type_text = str(event.get("typeText") or "")
    content_text = str(event.get("contentText") or "")
    if type_text == "userMessage":
      user_text = content_text
    elif type_text == "agentMessage" and user_text:
      dialogue.append((user_text, content_text))
      user_text = ""
  return dialogue


def create_orchestrator_state(context):
  event_list = context.get("eventList") if isinstance(context.get("eventList"), list) else []
  return {
    "metadata": {"templateKey": TEMPLATE_INFO["key"]},
    "eventList": event_list,
    "eventIndexLast": len(event_list) - 1,
    "messageText": str(context.get("messageText") or ""),
    "logDir": context.get("logDir"),
  }


def build_agent_event(state, reply_text, debug_info):
  return {
    "typeText": "agentMessage",
    "subtypeText": "textSimple",
    "contentType": 1,
    "contentText": reply_text,
    "metadata": {
      "templateKey": state["metadata"]["templateKey"],
      "debugInfo": debug_info,
    },
  }


def iter_orchestrator(state):
  dialogue = _to_dialogue(state["eventList"])
  turn_new, debug_info = generate_new_turn_with_live_fetch(
    dialogue,
    state["messageText"],
    is_return_debug=True,
    log_dir=state["logDir"],
  )
  yield build_agent_event(state, turn_new[1], debug_info)


def orchestrator_iter(context):
  state = create_orchestrator_state(context)
  yield from iter_orchestrator(state)
