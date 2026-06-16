from __future__ import annotations

from api_llm import ask_agent
from backend.config import get_model_service_config
from common import (
  build_initial_prompt,
  build_interactive_prompt,
  build_tool_result_structured_content,
  compose_continue_reply,
  compose_retry_reply,
  execute_tool_call,
  get_tools_remaining,
  parse_tool_call,
  reset_tool_status,
)

TEMPLATE_LIST = [
  {
    "key": "mcp-tool-all",
    "name": "MCP Tool Exercise",
    "description": "Asks the agent to try every available tool and lets the orchestrator handle tool results.",
  },
  {
    "key": "mcp-interactive",
    "name": "MCP Tool Exercise(Interactive)",
    "description": "Runs the MCP tool exercise first, then lets the user continue talking with tool support.",
  },
]

TEMPLATE_MODE_BY_KEY = {
  "mcp-tool-all": {
    "startupPromptType": "exercise",
    "isEncourageInvalidTool": True,
    "isAllowRepeatedTool": False,
    "isAllowTermination": False,
    "isExerciseMode": True,
  },
  "mcp-interactive": {
    "startupPromptType": "exercise",
    "isEncourageInvalidTool": True,
    "isAllowRepeatedTool": False,
    "isAllowTermination": False,
    "isExerciseMode": True,
  },
}


def _message_list_from_events(event_list):
  messages = []
  for event in event_list:
    type_text = str(event.get("typeText") or "")
    content_text = str(event.get("contentText") or "")
    if not content_text:
      continue
    if type_text == "agentMessage":
      role = "assistant"
    else:
      role = "user"
    messages.append({"role": role, "text": content_text})
  return messages


def _has_initial_prompt(event_list):
  for event in event_list:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    if metadata.get("isInitialPrompt") is True:
      return True
  return False


def _has_interactive_system_prompt(event_list):
  for event in event_list:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    if metadata.get("isInteractivePrompt") is True:
      return True
  return False


def _yield_text(type_text, content_text, metadata=None):
  return {
    "typeText": type_text,
    "subtypeText": "textSimple",
    "contentType": 1,
    "contentText": content_text,
    "metadata": metadata or {},
  }


def _build_startup_prompt(template_key, mode_config):
  if mode_config["startupPromptType"] == "exercise":
    return build_initial_prompt(is_encourage_invalid_tool=mode_config["isEncourageInvalidTool"])
  return build_interactive_prompt()


class McpToolOrchestrator:
  def __init__(self, template_key="mcp-interactive"):
    self.metadata = {"templateKey": template_key}
    self.event_list = []
    self.event_index_last = -1
    self.messages = []
    self.mode_config = TEMPLATE_MODE_BY_KEY.get(template_key) or TEMPLATE_MODE_BY_KEY["mcp-interactive"]

  def load(self, context):
    self.metadata["templateKey"] = str(context.get("templateKey") or self.metadata["templateKey"])
    self.event_list = context.get("eventList") or []
    self.event_index_last = len(self.event_list) - 1
    self.messages = _message_list_from_events(self.event_list)
    self.mode_config = TEMPLATE_MODE_BY_KEY.get(self.metadata["templateKey"]) or TEMPLATE_MODE_BY_KEY["mcp-interactive"]
    return self

  def initialize(self):
    reset_tool_status()
    prompt_initial = _build_startup_prompt(self.metadata["templateKey"], self.mode_config)
    self.messages.append({"role": "user", "text": prompt_initial})
    return _yield_text(
      "orchestratorMessage",
      prompt_initial,
      {"templateKey": self.metadata["templateKey"], "isInitialPrompt": True},
    )

  def iter(self):
    if not _has_initial_prompt(self.event_list):
      yield self.initialize()
      yield from self.iter_tool_loop()
      return
    if self.metadata["templateKey"] == "mcp-interactive":
      self.prepare_interactive_prompt()
      yield from self.iter_tool_loop()

  def prepare_interactive_prompt(self):
    if _has_interactive_system_prompt(self.event_list):
      return
    prompt_interactive = build_interactive_prompt()
    self.messages.insert(0, {"role": "user", "text": prompt_interactive})

  def iter_tool_loop(self):
    model_request_config = get_model_service_config()
    for _index in range(8):
      reply_agent = ask_agent(model_request_config, self.messages)
      self.messages.append({"role": "assistant", "text": reply_agent})
      tool_call, parse_error = parse_tool_call(
        reply_agent,
        is_allow_repeated_tool=self.mode_config["isAllowRepeatedTool"],
        is_allow_termination=self.mode_config["isAllowTermination"],
      )
      if tool_call is None:
        yield from self.iter_after_text_reply(reply_agent, parse_error)
        continue
      yield from self.iter_after_tool_call(reply_agent, tool_call, model_request_config)
      if self.is_tool_loop_done(tool_call):
        return

  def iter_after_text_reply(self, reply_agent, parse_error):
    if not self.mode_config["isExerciseMode"]:
      yield _yield_text("agentMessage", reply_agent, {"templateKey": self.metadata["templateKey"]})
      return
    reply_orchestrator = compose_retry_reply(parse_error)
    self.messages.append({"role": "user", "text": reply_orchestrator})
    yield _yield_text("agentMessage", reply_agent, {"templateKey": self.metadata["templateKey"], "isToolCallRejected": True})
    yield _yield_text("orchestratorMessage", reply_orchestrator, {"templateKey": self.metadata["templateKey"]})

  def iter_after_tool_call(self, reply_agent, tool_call, model_request_config):
    tool_name = tool_call["tool_name"]
    args = tool_call["args"]
    yield self.build_tool_call_event(reply_agent, tool_call, tool_name)
    try:
      result = execute_tool_call(tool_name, args)
    except Exception as error:
      reply_orchestrator = f"Tool execution failed: {error}. Please try again or answer naturally."
      self.messages.append({"role": "user", "text": reply_orchestrator})
      yield _yield_text("orchestratorMessage", reply_orchestrator, {"templateKey": self.metadata["templateKey"]})
      return
    yield self.build_tool_result_event(tool_name, result)
    if self.mode_config["isExerciseMode"] and not get_tools_remaining():
      reply_final = ask_agent(model_request_config, self.messages)
      yield _yield_text("agentMessage", reply_final, {"templateKey": self.metadata["templateKey"], "isFinal": True})

  def build_tool_call_event(self, reply_agent, tool_call, tool_name):
    return {
      "typeText": "agentMessage",
      "subtypeText": "toolCall",
      "contentType": 3,
      "contentText": reply_agent,
      "contentJson": tool_call,
      "metadata": {"templateKey": self.metadata["templateKey"], "toolName": tool_name},
    }

  def build_tool_result_event(self, tool_name, result):
    reply_orchestrator = compose_continue_reply(tool_name, result) if self.mode_config["isExerciseMode"] else f"Tool result: {result}"
    self.messages.append({"role": "user", "text": reply_orchestrator})
    return {
      "typeText": "orchestratorMessage",
      "subtypeText": "toolResult",
      "contentType": 3,
      "contentText": reply_orchestrator,
      "contentJson": build_tool_result_structured_content(
        tool_name,
        result,
        reply_text=reply_orchestrator,
        is_include_termination=self.mode_config["isAllowTermination"],
      ),
      "metadata": {"templateKey": self.metadata["templateKey"], "toolName": tool_name},
    }

  def is_tool_loop_done(self, tool_call):
    if tool_call["tool_name"] == "tool_terminate_conversation":
      return True
    return self.mode_config["isExerciseMode"] and not get_tools_remaining()


def orchestrator_iter(context):
  orchestrator = McpToolOrchestrator().load(context)
  yield from orchestrator.iter()
