from __future__ import annotations

import ast
import hashlib
import json
import operator
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
  sys.path.insert(0, str(ROOT_DIR))

from api_llm import ask_agent
from backend.config import get_model_service_config

MAX_TURNS_DEFAULT = 6

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

TOOL_LIST = [
  {
    "name": "tool_calculator",
    "description": "Calculate a basic arithmetic expression.",
    "args": {"expression": "string"},
  },
  {
    "name": "tool_str_md5",
    "description": "Calculate the MD5 hex digest of a string.",
    "args": {"text": "string"},
  },
  {
    "name": "tool_unix_timestamp",
    "description": "Return the current Unix timestamp in seconds.",
    "args": {},
  },
  {
    "name": "tool_return_to_parent",
    "description": "Return the final subagent result to the parent agent and end this subagent conversation.",
    "args": {
      "returnValue": "any json value",
      "summary": "string",
    },
  },
]


def _to_text(value):
  return str(value or "").strip()


def _yield_event(type_text, subtype_text, content_type, content_text, content_json=None, metadata=None):
  return {
    "typeText": type_text,
    "subtypeText": subtype_text,
    "contentType": content_type,
    "contentText": content_text,
    "contentJson": content_json,
    "metadata": metadata or {},
  }


def evaluate_arithmetic_node(node):
  if isinstance(node, ast.Expression):
    return evaluate_arithmetic_node(node.body)
  if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
    return node.value
  if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS_ALLOWED:
    return OPERATORS_ALLOWED[type(node.op)](
      evaluate_arithmetic_node(node.left),
      evaluate_arithmetic_node(node.right),
    )
  if isinstance(node, ast.UnaryOp) and type(node.op) in OPERATORS_ALLOWED:
    return OPERATORS_ALLOWED[type(node.op)](evaluate_arithmetic_node(node.operand))
  raise ValueError("Only numeric arithmetic expressions are supported.")


def tool_calculator(expression):
  return {
    "status": "success",
    "expression": expression,
    "result": evaluate_arithmetic_node(ast.parse(expression, mode="eval")),
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


def execute_tool(tool_name, args):
  args_data = args if isinstance(args, dict) else {}
  if tool_name == "tool_calculator":
    return tool_calculator(args_data["expression"])
  if tool_name == "tool_str_md5":
    return tool_str_md5(args_data["text"])
  if tool_name == "tool_unix_timestamp":
    return tool_unix_timestamp()
  if tool_name == "tool_return_to_parent":
    return {
      "status": "success",
      "isReturned": True,
      "returnValue": args_data.get("returnValue"),
      "summary": _to_text(args_data.get("summary")),
    }
  raise ValueError(f"Unknown tool: {tool_name}")


def parse_tool_call(reply_text):
  try:
    data = json.loads(reply_text)
  except json.JSONDecodeError as error:
    return None, f"JSON parse failed: {error}"
  if not isinstance(data, dict):
    return None, "Tool call must be a JSON object."
  if data.get("action") != "tool_call":
    return None, "The action field must be tool_call."
  tool_name = _to_text(data.get("tool_name"))
  if tool_name not in [tool["name"] for tool in TOOL_LIST]:
    return None, f"Unknown tool_name: {tool_name}"
  args = data.get("args")
  if not isinstance(args, dict):
    return None, "The args field must be an object."
  return {
    "tool_name": tool_name,
    "args": args,
  }, ""


def get_tools_description():
  line_list = []
  for tool in TOOL_LIST:
    line_list.append(f"- {tool['name']}: {tool['description']} args={json.dumps(tool['args'])}")
  return "\n".join(line_list)


def build_system_prompt(initial_prompt):
  return f"""
You are a subagent. Complete the task from the parent agent.

Available tools:
{get_tools_description()}

When you want to call a tool, reply only with JSON:
{{
  "action": "tool_call",
  "tool_name": "tool_name_here",
  "args": {{}}
}}

You must end by calling tool_return_to_parent. Put your final answer in args.returnValue and a short text summary in args.summary.
Do not launch subagents.

Task from parent:
{initial_prompt}
""".strip()


def build_tool_result_content(tool_name, result):
  return {
    "metadata": {
      "schemaVersion": 1,
      "kind": "toolResult",
      "toolName": tool_name,
    },
    "data": [
      {
        "type": "json",
        "data": result,
      },
    ],
  }


def build_subagent_return_result(is_returned, return_value, failure_reason, turn_count):
  return {
    "statusText": "completed" if is_returned else "failed",
    "isReturned": is_returned,
    "returnValue": return_value,
    "failureReason": failure_reason,
    "turnCount": turn_count,
  }


def orchestrator_iter(context):
  initial_prompt = _to_text(context.get("initialPrompt"))
  max_turns = int(context.get("maxTurns") or MAX_TURNS_DEFAULT)
  messages = [{"role": "user", "text": build_system_prompt(initial_prompt)}]
  yield _yield_event(
    "orchestratorMessage",
    "textSimple",
    1,
    messages[0]["text"],
    metadata={"templateKey": "subagent-basic", "isInitialPrompt": True},
  )

  model_config = get_model_service_config()
  for turn_index in range(max_turns):
    reply_agent = ask_agent(model_config, messages)
    messages.append({"role": "assistant", "text": reply_agent})
    tool_call, parse_error = parse_tool_call(reply_agent)
    if tool_call is None:
      reply_orchestrator = f"{parse_error}\nReply with a valid tool call JSON. You must eventually call tool_return_to_parent."
      messages.append({"role": "user", "text": reply_orchestrator})
      yield _yield_event(
        "agentMessage",
        "textSimple",
        1,
        reply_agent,
        metadata={"templateKey": "subagent-basic", "isToolCallRejected": True},
      )
      yield _yield_event(
        "orchestratorMessage",
        "textSimple",
        1,
        reply_orchestrator,
        metadata={"templateKey": "subagent-basic"},
      )
      continue

    tool_name = tool_call["tool_name"]
    yield _yield_event(
      "agentMessage",
      "toolCall",
      3,
      reply_agent,
      content_json=tool_call,
      metadata={"templateKey": "subagent-basic", "toolName": tool_name},
    )
    result = execute_tool(tool_name, tool_call["args"])
    if tool_name == "tool_return_to_parent":
      return_result = build_subagent_return_result(True, result.get("returnValue"), "", turn_index + 1)
      yield _yield_event(
        "orchestratorMessage",
        "subAgentReturn",
        3,
        json.dumps(return_result, ensure_ascii=False),
        content_json=return_result,
        metadata={"templateKey": "subagent-basic", "toolName": tool_name},
      )
      return

    reply_orchestrator = f"Tool result: {json.dumps(result, ensure_ascii=False)}"
    messages.append({"role": "user", "text": reply_orchestrator})
    yield _yield_event(
      "orchestratorMessage",
      "toolResult",
      3,
      reply_orchestrator,
      content_json=build_tool_result_content(tool_name, result),
      metadata={"templateKey": "subagent-basic", "toolName": tool_name},
    )

  return_result = build_subagent_return_result(
    False,
    None,
    "subagents still did not end talk with return value after maximum turns",
    max_turns,
  )
  yield _yield_event(
    "orchestratorMessage",
    "subAgentReturn",
    3,
    json.dumps(return_result, ensure_ascii=False),
    content_json=return_result,
    metadata={"templateKey": "subagent-basic"},
  )
