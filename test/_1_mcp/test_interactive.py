import json
import sys
from pathlib import Path

from common import build_interactive_prompt, execute_tool_call, parse_tool_call
from api_llm import ask_agent
from backend.config import get_model_service_config

THIS_DIR = Path(__file__).resolve().parent
TEST_DIR = THIS_DIR.parent
if str(TEST_DIR) not in sys.path:
  sys.path.insert(0, str(TEST_DIR))

from test_utils import (
  append_message,
  build_time_stamp,
  format_tool_result_for_print,
  is_tool_call_agent_reply,
  print_section,
  shorten_text,
  try_write_backend_conversation_log,
  write_conversation_log,
)


def is_tool_call_like(reply_text):
  return is_tool_call_agent_reply(reply_text)


def build_tool_result_reply(tool_name, result):
  result_text = json.dumps(result, ensure_ascii=False)
  return f"Tool result: {result_text}"


def save_interactive_log(messages, final_status):
  log_path = THIS_DIR / f"{build_time_stamp()}_conversation_interactive.md"
  write_conversation_log(log_path, messages, final_status)
  print_section("Saved Conversation Log", str(log_path))
  try_write_backend_conversation_log(messages, final_status, "_1_mcp interactive conversation", "_1_mcp")


def run_interactive_conversation():
  model_request_config = get_model_service_config()
  messages = []
  append_message(messages, "user", build_interactive_prompt(), event_type="orchestratorMessage")
  print_section("Interactive Prompt", messages[-1]["text"])

  while True:
    reply_agent = ask_agent(model_request_config, messages)
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
