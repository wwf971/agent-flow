from __future__ import annotations

from typing import Any

from .google import generate_text_google


def generate_text(request_data: dict[str, Any]):
    provider_name = str(request_data.get("providerName") or "google").strip().lower()
    if provider_name == "google":
        return generate_text_google(request_data)
    raise RuntimeError(f"LLM provider is not supported: {provider_name}")
