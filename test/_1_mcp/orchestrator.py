from __future__ import annotations

from api_llm import ask_agent
from backend.config import get_model_service_config
from common import (
  build_initial_prompt,
  build_interactive_prompt,
  build_tool_result_structured_content,
  compose_continue_reply,
  compose_retry_reply,
  create_tool_status,
  execute_tool_call,
  get_tools_called,
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

TEMPLATE_MODE_INTERACTIVE_TURN = {
  "startupPromptType": "interactive",
  "isEncourageInvalidTool": False,
  "isAllowRepeatedTool": True,
  "isAllowTermination": True,
  "isExerciseMode": False,
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


def _build_tool_status_from_events(event_list):
  tool_status = create_tool_status()
  for event in event_list:
    if event.get("subtypeText") != "toolResult":
      continue
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    tool_name = str(metadata.get("toolName") or "")
    if tool_name and tool_name not in get_tools_called(tool_status):
      tool_status["toolCalledList"].append(tool_name)
  tool_status["toolRemainingList"][:] = get_tools_remaining(tool_status)
  return tool_status


def _yield_text(type_text, content_text, metadata=None):
  return {
    "typeText": type_text,
    "subtypeText": "textSimple",
    "contentType": 1,
    "contentText": content_text,
    "metadata": metadata or {},
  }


def _build_startup_prompt(template_key, mode_config, backend_tool_list=None):
  if mode_config["startupPromptType"] == "exercise":
    return build_initial_prompt(
      is_encourage_invalid_tool=mode_config["isEncourageInvalidTool"],
      tool_list_extra=backend_tool_list,
    )
  return build_interactive_prompt(backend_tool_list)


def create_orchestrator_state(context):
  template_key = str(context.get("templateKey") or "mcp-interactive")
  event_list = context.get("eventList") if isinstance(context.get("eventList"), list) else []
  backend_tool_list = context.get("backendToolList")
  return {
    "metadata": {"templateKey": template_key},
    "eventList": event_list,
    "eventIndexLast": len(event_list) - 1,
    "messages": _message_list_from_events(event_list),
    "modeConfig": TEMPLATE_MODE_BY_KEY.get(template_key) or TEMPLATE_MODE_BY_KEY["mcp-interactive"],
    "backendToolList": backend_tool_list if isinstance(backend_tool_list, list) else [],
    "executeBackendTool": context.get("executeBackendTool"),
    "toolStatus": _build_tool_status_from_events(event_list),
  }


def iter_orchestrator(state):
  if not _has_initial_prompt(state["eventList"]):
    yield initialize_orchestrator(state)
    yield from iter_tool_loop(state)
    return
  if state["metadata"]["templateKey"] == "mcp-interactive":
    prepare_interactive_prompt(state)
    yield from iter_tool_loop(state)


def initialize_orchestrator(state):
  reset_tool_status(state["toolStatus"])
  prompt_initial = _build_startup_prompt(state["metadata"]["templateKey"], state["modeConfig"], state["backendToolList"])
  state["messages"].append({"role": "user", "text": prompt_initial})
  return _yield_text(
    "orchestratorMessage",
    prompt_initial,
    {"templateKey": state["metadata"]["templateKey"], "isInitialPrompt": True},
  )


def prepare_interactive_prompt(state):
  state["modeConfig"] = dict(TEMPLATE_MODE_INTERACTIVE_TURN)
  if _has_interactive_system_prompt(state["eventList"]):
    return
  prompt_interactive = build_interactive_prompt(state["backendToolList"])
  state["messages"].insert(0, {"role": "user", "text": prompt_interactive})


def iter_tool_loop(state):
  model_request_config = get_model_service_config()
  for _index in range(8):
    reply_agent = ask_agent(model_request_config, state["messages"])
    state["messages"].append({"role": "assistant", "text": reply_agent})
    tool_call, parse_error = parse_tool_call(
      reply_agent,
      is_allow_repeated_tool=state["modeConfig"]["isAllowRepeatedTool"],
      is_allow_termination=state["modeConfig"]["isAllowTermination"],
      tool_list_extra=state["backendToolList"],
      tool_status=state["toolStatus"],
    )
    if tool_call is None:
      yield from iter_after_text_reply(state, reply_agent, parse_error)
      if not state["modeConfig"]["isExerciseMode"]:
        return
      continue
    yield from iter_after_tool_call(state, reply_agent, tool_call, model_request_config)
    if is_tool_loop_done(state, tool_call):
      return


def iter_after_text_reply(state, reply_agent, parse_error):
  if not state["modeConfig"]["isExerciseMode"]:
    yield _yield_text("agentMessage", reply_agent, {"templateKey": state["metadata"]["templateKey"]})
    return
  reply_orchestrator = compose_retry_reply(parse_error, state["toolStatus"])
  state["messages"].append({"role": "user", "text": reply_orchestrator})
  yield _yield_text("agentMessage", reply_agent, {"templateKey": state["metadata"]["templateKey"], "isToolCallRejected": True})
  yield _yield_text("orchestratorMessage", reply_orchestrator, {"templateKey": state["metadata"]["templateKey"]})


def iter_after_tool_call(state, reply_agent, tool_call, model_request_config):
  tool_name = tool_call["tool_name"]
  args = tool_call["args"]
  yield build_tool_call_event(state, reply_agent, tool_call, tool_name)
  try:
    if is_backend_tool(state, tool_name):
      result = yield from state["executeBackendTool"](tool_name, args)
    else:
      result = execute_tool_call(tool_name, args)
  except Exception as error:
    reply_orchestrator = f"Tool execution failed: {error}. Please try again or answer naturally."
    state["messages"].append({"role": "user", "text": reply_orchestrator})
    yield _yield_text("orchestratorMessage", reply_orchestrator, {"templateKey": state["metadata"]["templateKey"]})
    return
  yield build_tool_result_event(state, tool_name, result)
  if state["modeConfig"]["isExerciseMode"] and not get_tools_remaining(state["toolStatus"]):
    reply_final = ask_agent(model_request_config, state["messages"])
    yield _yield_text("agentMessage", reply_final, {"templateKey": state["metadata"]["templateKey"], "isFinal": True})


def build_tool_call_event(state, reply_agent, tool_call, tool_name):
  return {
    "typeText": "agentMessage",
    "subtypeText": "toolCall",
    "contentType": 3,
    "contentText": reply_agent,
    "contentJson": tool_call,
    "metadata": {"templateKey": state["metadata"]["templateKey"], "toolName": tool_name},
  }


def build_tool_result_event(state, tool_name, result):
  if state["modeConfig"]["isExerciseMode"]:
    reply_orchestrator = compose_continue_reply(tool_name, result, state["toolStatus"])
  else:
    reply_orchestrator = f"Tool result: {result}"
  state["messages"].append({"role": "user", "text": reply_orchestrator})
  return {
    "typeText": "orchestratorMessage",
    "subtypeText": "toolResult",
    "contentType": 3,
    "contentText": reply_orchestrator,
    "contentJson": build_tool_result_structured_content(
      tool_name,
      result,
      reply_text=reply_orchestrator,
      is_include_termination=state["modeConfig"]["isAllowTermination"],
      tool_list_extra=state["backendToolList"],
    ),
    "metadata": {"templateKey": state["metadata"]["templateKey"], "toolName": tool_name},
  }


def is_backend_tool(state, tool_name):
  if not callable(state["executeBackendTool"]):
    return False
  return tool_name in [tool.get("name") for tool in state["backendToolList"] if isinstance(tool, dict)]


def is_tool_loop_done(state, tool_call):
  if tool_call["tool_name"] == "tool_terminate_conversation":
    return True
  return state["modeConfig"]["isExerciseMode"] and not get_tools_remaining(state["toolStatus"])


def orchestrator_iter(context):
  state = create_orchestrator_state(context)
  yield from iter_orchestrator(state)
