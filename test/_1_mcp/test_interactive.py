import json

from promp_tool import build_interactive_prompt
from tool_example import execute_tool_call, parse_tool_call
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


def is_tool_call_like(reply_text):
  try:
    data = json.loads(reply_text)
  except json.JSONDecodeError:
    return False
  return isinstance(data, dict) and data.get("action") == "tool_call"


def build_tool_result_reply(tool_name, result):
  result_text = json.dumps(result, ensure_ascii=False)
  return f"Tool result: {result_text}"


def save_interactive_log(messages, final_status):
  log_path = THIS_DIR / f"{build_time_stamp()}_conversation_interactive.md"
  write_conversation_log(log_path, messages, final_status)
  print_section("Saved Conversation Log", str(log_path))
  try_write_backend_conversation_log(messages, final_status, "_1_mcp interactive conversation")


def run_interactive_conversation():
  client, model_name = build_client_and_model()
  messages = []
  append_message(messages, "user", build_interactive_prompt(), event_type="orchestratorMessage")
  print_section("Interactive Prompt", messages[-1]["text"])

  while True:
    reply_agent = ask_agent(client, model_name, messages)
    append_message(messages, "assistant", reply_agent)
    print_section("Agent", reply_agent)

    tool_call, parse_error = parse_tool_call(
      reply_agent,
      is_allow_repeated_tool=True,
      is_allow_termination=True,
    )
    if tool_call is not None:
      tool_name = tool_call["tool_name"]
      args = tool_call["args"]
      try:
        result = execute_tool_call(tool_name, args)
      except Exception as e:
        reply_orchestrator = f"Tool execution failed: {e}. Please try again or answer naturally."
        append_message(messages, "user", reply_orchestrator, event_type="orchestratorMessage")
        print_section("Orchestrator", reply_orchestrator)
        continue

      print_section(f"Tool Result: {tool_name}", format_tool_result_for_print(result))
      reply_orchestrator = build_tool_result_reply(tool_name, result)
      append_message(messages, "user", reply_orchestrator, event_type="orchestratorMessage")
      print_section("Orchestrator", shorten_text(reply_orchestrator, limit=1200))

      if tool_name == "tool_terminate_conversation":
        save_interactive_log(messages, "agent_terminated")
        return
      continue

    if is_tool_call_like(reply_agent):
      reply_orchestrator = f"Invalid tool call: {parse_error}. Please try again or answer naturally."
      append_message(messages, "user", reply_orchestrator, event_type="orchestratorMessage")
      print_section("Orchestrator", reply_orchestrator)
      continue

    user_text = input("\nYou: ").strip()
    if user_text == "/exit":
      save_interactive_log(messages, "user_exit")
      return
    append_message(messages, "user", user_text)


if __name__ == "__main__":
  run_interactive_conversation()
