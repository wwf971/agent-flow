from __future__ import annotations

from promp_tool import build_initial_prompt, build_interactive_prompt
from tool_example import (
  build_tool_result_structured_content,
  compose_continue_reply,
  compose_retry_reply,
  execute_tool_call,
  get_tools_remaining,
  parse_tool_call,
  reset_tool_status,
)
from test_utils import ask_agent, build_client_and_model

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


def _run_tool_loop(messages, is_allow_repeated_tool, is_allow_termination, template_key, is_exercise_mode=False):
  client, model_name = build_client_and_model()
  for _index in range(8):
    reply_agent = ask_agent(client, model_name, messages)
    messages.append({"role": "assistant", "text": reply_agent})
    tool_call, parse_error = parse_tool_call(
      reply_agent,
      is_allow_repeated_tool=is_allow_repeated_tool,
      is_allow_termination=is_allow_termination,
    )
    if tool_call is None:
      if is_exercise_mode:
        reply_orchestrator = compose_retry_reply(parse_error)
        messages.append({"role": "user", "text": reply_orchestrator})
        yield _yield_text("agentMessage", reply_agent, {"templateKey": template_key, "isToolCallRejected": True})
        yield _yield_text("orchestratorMessage", reply_orchestrator, {"templateKey": template_key})
        continue
      yield _yield_text("agentMessage", reply_agent, {"templateKey": template_key})
      return

    tool_name = tool_call["tool_name"]
    args = tool_call["args"]
    yield {
      "typeText": "agentMessage",
      "subtypeText": "toolCall",
      "contentType": 3,
      "contentText": reply_agent,
      "contentJson": tool_call,
      "metadata": {"templateKey": template_key, "toolName": tool_name},
    }
    try:
      result = execute_tool_call(tool_name, args)
    except Exception as error:
      reply_orchestrator = f"Tool execution failed: {error}. Please try again or answer naturally."
      messages.append({"role": "user", "text": reply_orchestrator})
      yield _yield_text("orchestratorMessage", reply_orchestrator, {"templateKey": template_key})
      continue

    if is_exercise_mode:
      reply_orchestrator = compose_continue_reply(tool_name, result)
    else:
      reply_orchestrator = f"Tool result: {result}"
    messages.append({"role": "user", "text": reply_orchestrator})
    yield {
      "typeText": "orchestratorMessage",
      "subtypeText": "toolResult",
      "contentType": 3,
      "contentText": reply_orchestrator,
      "contentJson": build_tool_result_structured_content(
        tool_name,
        result,
        reply_text=reply_orchestrator,
        is_include_termination=is_allow_termination,
      ),
      "metadata": {"templateKey": template_key, "toolName": tool_name},
    }

    if tool_name == "tool_terminate_conversation":
      return
    if is_exercise_mode and not get_tools_remaining():
      reply_final = ask_agent(client, model_name, messages)
      yield _yield_text("agentMessage", reply_final, {"templateKey": template_key, "isFinal": True})
      return


def orchestrator_iter(context):
  template_key = str(context.get("templateKey") or "mcp-interactive")
  event_list = context.get("eventList") or []
  messages = _message_list_from_events(event_list)
  mode_config = TEMPLATE_MODE_BY_KEY.get(template_key) or TEMPLATE_MODE_BY_KEY["mcp-interactive"]
  if not _has_initial_prompt(event_list):
    reset_tool_status()
    prompt_initial = _build_startup_prompt(template_key, mode_config)
    messages.append({"role": "user", "text": prompt_initial})
    yield _yield_text("orchestratorMessage", prompt_initial, {"templateKey": template_key, "isInitialPrompt": True})
    yield from _run_tool_loop(
      messages,
      mode_config["isAllowRepeatedTool"],
      mode_config["isAllowTermination"],
      template_key,
      mode_config["isExerciseMode"],
    )
    return
  if template_key == "mcp-interactive":
    if not _has_interactive_system_prompt(event_list):
      prompt_interactive = build_interactive_prompt()
      messages.insert(0, {"role": "user", "text": prompt_interactive})
    yield from _run_tool_loop(messages, True, True, "mcp-interactive")
