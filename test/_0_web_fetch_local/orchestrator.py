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


class WebFetchLocalOrchestrator:
  def __init__(self):
    self.metadata = {"templateKey": TEMPLATE_INFO["key"]}
    self.event_list = []
    self.event_index_last = -1
    self.message_text = ""
    self.log_dir = None

  def load(self, context):
    self.event_list = context.get("eventList") or []
    self.event_index_last = len(self.event_list) - 1
    self.message_text = str(context.get("messageText") or "")
    self.log_dir = context.get("logDir")
    return self

  def initialize(self):
    self.metadata = {"templateKey": TEMPLATE_INFO["key"]}
    self.event_list = []
    self.event_index_last = -1
    return self

  def iter(self):
    dialogue = _to_dialogue(self.event_list)
    _turn_new, debug_info = generate_new_turn_with_live_fetch(
      dialogue,
      self.message_text,
      is_return_debug=True,
      log_dir=self.log_dir,
    )
    yield self.build_agent_event(_turn_new[1], debug_info)

  def build_agent_event(self, reply_text, debug_info):
    return {
      "typeText": "agentMessage",
      "subtypeText": "textSimple",
      "contentType": 1,
      "contentText": reply_text,
      "metadata": {
        "templateKey": self.metadata["templateKey"],
        "debugInfo": debug_info,
      },
    }


def orchestrator_iter(context):
  orchestrator = WebFetchLocalOrchestrator().load(context)
  yield from orchestrator.iter()
