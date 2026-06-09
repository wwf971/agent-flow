from __future__ import annotations

from test import generate_new_turn_with_live_fetch


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


def orchestrator_iter(context):
  event_list = context.get("eventList") or []
  message_text = str(context.get("messageText") or "")
  dialogue = _to_dialogue(event_list)
  _turn_new, debug_info = generate_new_turn_with_live_fetch(
    dialogue,
    message_text,
    is_return_debug=True,
    log_dir=context.get("logDir"),
  )
  reply_text = _turn_new[1]
  yield {
    "typeText": "agentMessage",
    "subtypeText": "textSimple",
    "contentType": 1,
    "contentText": reply_text,
    "metadata": {
      "templateKey": TEMPLATE_INFO["key"],
      "debugInfo": debug_info,
    },
  }
