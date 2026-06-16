from __future__ import annotations

from typing import Any

from .api_llm import generate_text


def build_text_from_messages(message_list: list[dict[str, Any]]):
    line_list = []
    for message in message_list:
        role_text = message["role"]
        content_text = message["text"]
        line_list.append(f"{role_text.upper()}:\n{content_text}")
    return "\n\n".join(line_list)


def ask_agent(model_request_config: dict[str, Any], message_list: list[dict[str, Any]]):
    reply_text = generate_text({
        **model_request_config,
        "textInput": build_text_from_messages(message_list),
        "temperature": 0.0,
    })
    return reply_text.strip()
