from promp_tool import build_initial_prompt
from tool_example import (
  compose_continue_reply,
  compose_retry_reply,
  execute_tool_call,
  get_tools_called,
  get_tools_remaining,
  parse_tool_call,
  reset_tool_status,
)
from test_utils import (
  THIS_DIR,
  append_message,
  ask_agent,
  build_client_and_model,
  build_time_stamp,
  format_tool_result_for_print,
  print_section,
  shorten_text,
  try_write_backend_conversation_log,
  write_conversation_log,
)

MAX_ATTEMPTS = 10


def run_tool_experiment():
  reset_tool_status()
  client, model_name = build_client_and_model()
  messages = []
  append_message(messages, "user", build_initial_prompt(is_encourage_invalid_tool=True), event_type="orchestratorMessage")
  print_section("Initial Prompt", messages[-1]["text"])

  final_status = "stopped"
  for attempt_index in range(1, MAX_ATTEMPTS + 1):
    reply_agent = ask_agent(client, model_name, messages)
    append_message(messages, "assistant", reply_agent)
    print_section(f"Agent Reply {attempt_index}", reply_agent)

    tool_call, parse_error = parse_tool_call(reply_agent)
    if tool_call is None:
      reply_orchestrator = compose_retry_reply(parse_error)
      append_message(messages, "user", reply_orchestrator, event_type="orchestratorMessage")
      print_section("Orchestrator Reply", reply_orchestrator)
      continue

    tool_name = tool_call["tool_name"]
    args = tool_call["args"]
    try:
      result = execute_tool_call(tool_name, args)
    except Exception as e:
      reply_orchestrator = compose_retry_reply(f"Tool execution failed: {e}")
      append_message(messages, "user", reply_orchestrator, event_type="orchestratorMessage")
      print_section("Orchestrator Reply", reply_orchestrator)
      continue

    print_section(f"Tool Result: {tool_name}", format_tool_result_for_print(result))
    reply_orchestrator = compose_continue_reply(tool_name, result)
    append_message(messages, "user", reply_orchestrator, event_type="orchestratorMessage")
    print_section("Orchestrator Reply", shorten_text(reply_orchestrator, limit=1200))

    if not get_tools_remaining():
      final_status = "all_tools_completed"
      reply_final = ask_agent(client, model_name, messages)
      append_message(messages, "assistant", reply_final)
      print_section("Final Agent Summary", reply_final)
      break

  if get_tools_remaining():
    final_status = "max_attempts_reached"
    print_section("Closed", f"Remaining tools: {', '.join(get_tools_remaining())}")

  log_path = THIS_DIR / f"{build_time_stamp()}_conversation.txt"
  write_conversation_log(log_path, messages, final_status)
  print_section("Saved Conversation Log", str(log_path))
  try_write_backend_conversation_log(messages, final_status, "_1_mcp tool experiment")
  print_section("Tools Completed", ", ".join(get_tools_called()) or "none")


if __name__ == "__main__":
  run_tool_experiment()
