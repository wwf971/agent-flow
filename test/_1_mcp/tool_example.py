



import ast
import hashlib
import json
import operator
import sys
import time
from pathlib import Path

SITE_EXAMPLE = "https://transit.yahoo.co.jp/diainfo/area/4"

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
  sys.path.insert(0, str(ROOT_DIR))
from tool_web_fetch import tool_web_fetch

REPLY_TOOL_RETURN_VALUE_EXAMPLE = json.dumps({
  "status": "success",
  "data": {
    "key": "value"
  }
})
TOOL_CALL_FORMAT_EXAMPLE = json.dumps({
  "action": "tool_call",
  "tool_name": "tool_calculator",
  "args": {
    "expression": "12 * (3 + 4)"
  }
})
REPLY_WRONG_TOOL_CALL_FORMAT = (
  "That was not a valid tool call. Reply with only JSON in this shape: "
  f"{TOOL_CALL_FORMAT_EXAMPLE}"
)

TOOLS_LIST = [
  {
    "name": "tool_web_fetch",
    "description": f"Fetch main readable website content. Use it with url={SITE_EXAMPLE}.",
    "args": {
      "url": "string",
      "char_num_max": "optional integer",
    },
    "example_args": {
      "url": SITE_EXAMPLE,
      "char_num_max": 4000,
    },
    "outputSchema": {
      "type": "object",
      "properties": {
        "status": {"type": "string"},
        "url": {"type": "string"},
        "text": {"type": "string"},
        "char_num": {"type": "integer"},
        "char_num_max": {"type": "integer"},
        "is_clipped": {"type": "boolean"},
        "char_index_start": {"type": "integer"},
        "char_index_end": {"type": "integer"},
        "error": {"type": "string"},
      },
    },
    "displayRules": {
      "text": "popup",
    },
  },
  {
    "name": "tool_calculator",
    "description": "Calculate a basic arithmetic expression.",
    "args": {
      "expression": "string",
    },
    "example_args": {
      "expression": "25 * (8 + 2)",
    },
    "outputSchema": {
      "type": "object",
      "properties": {
        "status": {"type": "string"},
        "expression": {"type": "string"},
        "result": {"type": ["number", "integer"]},
      },
    },
  },
  {
    "name": "tool_str_md5",
    "description": "Calculate the MD5 hex digest of a string.",
    "args": {
      "text": "string",
    },
    "example_args": {
      "text": "hello",
    },
    "outputSchema": {
      "type": "object",
      "properties": {
        "status": {"type": "string"},
        "text": {"type": "string"},
        "md5": {"type": "string"},
      },
    },
  },
  {
    "name": "tool_unix_timestamp",
    "description": "Return the current Unix timestamp in seconds.",
    "args": {},
    "example_args": {},
    "outputSchema": {
      "type": "object",
      "properties": {
        "status": {"type": "string"},
        "unix_timestamp": {"type": "integer"},
      },
    },
  },
]
TOOL_TERMINATE_CONVERSATION = {
  "name": "tool_terminate_conversation",
  "description": "Terminate the current interactive conversation when the user says bye or expresses a similar intent.",
  "args": {
    "reason": "string",
  },
  "example_args": {
    "reason": "The user said bye.",
  },
  "outputSchema": {
    "type": "object",
    "properties": {
      "status": {"type": "string"},
      "is_terminated": {"type": "boolean"},
      "reason": {"type": "string"},
    },
  },
  "displayRules": {
    "reason": "popup",
  },
}

TOOLS_CALLED = []
TOOLS_REMAINING = [tool["name"] for tool in TOOLS_LIST]

OPERATORS_ALLOWED = {
  ast.Add: operator.add,
  ast.Sub: operator.sub,
  ast.Mult: operator.mul,
  ast.Div: operator.truediv,
  ast.FloorDiv: operator.floordiv,
  ast.Mod: operator.mod,
  ast.Pow: operator.pow,
  ast.USub: operator.neg,
  ast.UAdd: operator.pos,
}


def build_tool_call_json(tool_name, args):
  return json.dumps({
    "action": "tool_call",
    "tool_name": tool_name,
    "args": args,
  }, ensure_ascii=False, indent=2)


def get_tools_description(is_include_termination=False):
  lines = []
  tools = list(TOOLS_LIST)
  if is_include_termination:
    tools.append(TOOL_TERMINATE_CONVERSATION)
  for tool in tools:
    args_text = json.dumps(tool["args"])
    lines.append(f"- {tool['name']}: {tool['description']} args={args_text}")
  return "\n".join(lines)


def get_tool_call_examples(is_include_termination=False):
  tools = list(TOOLS_LIST)
  if is_include_termination:
    tools.append(TOOL_TERMINATE_CONVERSATION)
  return "\n\n".join(build_tool_call_json(tool["name"], tool["example_args"]) for tool in tools)


def get_tool_definition(tool_name, is_include_termination=False):
  tools = list(TOOLS_LIST)
  if is_include_termination:
    tools.append(TOOL_TERMINATE_CONVERSATION)
  for tool in tools:
    if tool["name"] == tool_name:
      return tool
  return None


def build_tool_result_structured_content(tool_name, result, reply_text=None, is_include_termination=False):
  tool_definition = get_tool_definition(tool_name, is_include_termination=is_include_termination) or {}
  result_text = json.dumps(result, ensure_ascii=False)
  text_prefix = "Tool result: "
  text_suffix = ""
  if isinstance(reply_text, str) and result_text in reply_text:
    prefix, suffix = reply_text.split(result_text, 1)
    text_prefix = prefix
    text_suffix = suffix
  return {
    "metadata": {
      "schemaVersion": 1,
      "kind": "toolResult",
      "toolName": tool_name,
    },
    "data": [
      {
        "type": "text",
        "data": text_prefix,
      },
      {
        "type": "json",
        "data": result,
        "outputSchema": tool_definition.get("outputSchema") or {},
        "displayRules": tool_definition.get("displayRules") or {},
      },
      {
        "type": "text",
        "data": text_suffix,
      },
    ],
  }


def build_tool_result_segment(tool_name, result, is_include_termination=False):
  return build_tool_result_structured_content(
    tool_name,
    result,
    is_include_termination=is_include_termination,
  )


def get_tools_called():
  return list(TOOLS_CALLED)


def get_tools_remaining():
  return [tool["name"] for tool in TOOLS_LIST if tool["name"] not in TOOLS_CALLED]


def reset_tool_status():
  TOOLS_CALLED.clear()
  TOOLS_REMAINING[:] = [tool["name"] for tool in TOOLS_LIST]


def remember_tool_called(tool_name):
  if tool_name not in TOOLS_CALLED:
    TOOLS_CALLED.append(tool_name)
  TOOLS_REMAINING[:] = get_tools_remaining()


def compose_retry_reply(reason):
  remaining = ", ".join(get_tools_remaining())
  return (
    f"{reason}\n"
    f"{REPLY_WRONG_TOOL_CALL_FORMAT}\n"
    f"Tools already completed: {', '.join(get_tools_called()) or 'none'}.\n"
    f"Please try one remaining tool: {remaining}."
  )


def compose_continue_reply(tool_name, result):
  remember_tool_called(tool_name)
  remaining = get_tools_remaining()
  result_text = json.dumps(result, ensure_ascii=False)
  if not remaining:
    return f"Tool result: {result_text}\nAll tools have been completed. Reply with a short natural language summary."
  return (
    f"Tool result: {result_text}\n"
    f"Tools already completed: {', '.join(get_tools_called())}.\n"
    f"Please try one remaining tool using the required JSON format: {', '.join(remaining)}."
  )


def evaluate_arithmetic_node(node):
  if isinstance(node, ast.Expression):
    return evaluate_arithmetic_node(node.body)
  if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
    return node.value
  if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS_ALLOWED:
    left = evaluate_arithmetic_node(node.left)
    right = evaluate_arithmetic_node(node.right)
    return OPERATORS_ALLOWED[type(node.op)](left, right)
  if isinstance(node, ast.UnaryOp) and type(node.op) in OPERATORS_ALLOWED:
    operand = evaluate_arithmetic_node(node.operand)
    return OPERATORS_ALLOWED[type(node.op)](operand)
  raise ValueError("Only numeric arithmetic expressions are supported.")


def tool_calculator(expression):
  tree = ast.parse(expression, mode="eval")
  result = evaluate_arithmetic_node(tree)
  return {
    "status": "success",
    "expression": expression,
    "result": result,
  }


def tool_str_md5(text):
  return {
    "status": "success",
    "text": text,
    "md5": hashlib.md5(text.encode("utf-8")).hexdigest(),
  }


def tool_unix_timestamp():
  return {
    "status": "success",
    "unix_timestamp": int(time.time()),
  }


def tool_terminate_conversation(reason):
  return {
    "status": "success",
    "is_terminated": True,
    "reason": reason,
  }


def execute_tool_call(tool_name, args):
  if tool_name == "tool_web_fetch":
    return tool_web_fetch(
      args.get("url", SITE_EXAMPLE),
      char_num_max=int(args.get("char_num_max", 30000)),
    )
  if tool_name == "tool_calculator":
    return tool_calculator(args["expression"])
  if tool_name == "tool_str_md5":
    return tool_str_md5(args["text"])
  if tool_name == "tool_unix_timestamp":
    return tool_unix_timestamp()
  if tool_name == "tool_terminate_conversation":
    return tool_terminate_conversation(args.get("reason", "The agent requested conversation termination."))
  raise ValueError(f"Unknown tool: {tool_name}")


def parse_tool_call(reply_text, is_allow_repeated_tool=False, is_allow_termination=False):
  try:
    data = json.loads(reply_text)
  except json.JSONDecodeError as e:
    return None, f"JSON parse failed: {e}"

  if not isinstance(data, dict):
    return None, "Tool call must be a JSON object."
  if data.get("action") != "tool_call":
    return None, "The action field must be tool_call."

  tool_name = data.get("tool_name")
  tool_names = [tool["name"] for tool in TOOLS_LIST]
  if is_allow_termination:
    tool_names.append(TOOL_TERMINATE_CONVERSATION["name"])
  if tool_name not in tool_names:
    return None, f"Unknown tool_name: {tool_name}"
  if not is_allow_repeated_tool and tool_name in TOOLS_CALLED:
    return None, f"The tool {tool_name} was already completed. Choose a remaining tool."

  args = data.get("args")
  if not isinstance(args, dict):
    return None, "The args field must be an object."
  return {
    "tool_name": tool_name,
    "args": args,
  }, ""