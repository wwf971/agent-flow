from __future__ import annotations

from typing import Any


def generate_text_google(request_data: dict[str, Any]):
    api_key = str(request_data.get("apiKey") or "")
    model_name = str(request_data.get("modelName") or "gemini-2.5-flash")
    text_input = str(request_data.get("textInput") or "")
    system_instruction = str(request_data.get("systemInstruction") or "")
    temperature = float(request_data.get("temperature") or 0.0)
    if not api_key:
        raise RuntimeError("google api key is not configured")

    from google import genai
    from google.genai import types

    config_data = {
        "temperature": temperature,
    }
    if system_instruction:
        config_data["system_instruction"] = system_instruction

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=text_input,
        config=types.GenerateContentConfig(**config_data),
    )
    return response.text or ""
