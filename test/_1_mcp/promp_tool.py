from tool_example import SITE_EXAMPLE, get_tool_call_examples, get_tools_description


def build_initial_prompt(is_encourage_invalid_tool=False):
  invalid_tool_text = ""
  if is_encourage_invalid_tool:
    invalid_tool_text = """

Before completing all valid tools, intentionally try one non-existing tool once.
This lets the orchestrator test its unknown-tool handling.
After the orchestrator rejects it, continue with real tools.
""".rstrip()

  return f"""
You are testing a simple tool execution orchestrator.

Your goal is to try every available tool exactly once.
{invalid_tool_text}

Available tools:
{get_tools_description()}

You must visit this site by using tool_web_fetch:
{SITE_EXAMPLE}

When you want to execute a tool, reply with only standard JSON.
Do not wrap JSON in markdown.
Do not include natural language around the JSON.

Required tool call format:
{{
  "action": "tool_call",
  "tool_name": "tool_name_here",
  "args": {{
    "argument_name": "argument_value"
  }}
}}

Examples:
{get_tool_call_examples()}

After each valid tool call, the orchestrator will return the tool result and tell you which tools remain.
If your tool call JSON is invalid, the orchestrator will guide you to try again.
Start now by calling one tool.
""".strip()


def build_interactive_prompt():
  return f"""
You are an assistant inside an interactive tool-calling experiment.

You can reply in natural language when no tool is needed.
When a tool is useful, reply with only standard JSON in the required tool call format.

Available tools:
{get_tools_description(is_include_termination=True)}

Required tool call format:
{{
  "action": "tool_call",
  "tool_name": "tool_name_here",
  "args": {{
    "argument_name": "argument_value"
  }}
}}

Examples:
{get_tool_call_examples(is_include_termination=True)}

If the user says bye, goodbye, see you, or expresses similar meaning, call tool_terminate_conversation.
Do not terminate by yourself unless the user clearly wants to end the conversation.
""".strip()
