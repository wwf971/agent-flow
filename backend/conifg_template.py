from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from config import get_dir_base
from templates import TEMPLATE_LIST

DIR_BASE = get_dir_base()

TEMPLATE_FALLBACK = dict(TEMPLATE_LIST[0])


def list_templates():
    return [dict(item) for item in TEMPLATE_LIST]


def get_template_by_key(template_key: str):
    normalized_key = str(template_key or "free-talk").strip() or "free-talk"
    for item in TEMPLATE_LIST:
        if item["key"] == normalized_key:
            return dict(item)
    return dict(TEMPLATE_FALLBACK)


def load_template_module(template_key: str):
    template = get_template_by_key(template_key)
    module_path_text = str(template.get("modulePath") or "")
    if not module_path_text:
        return None
    module_path = DIR_BASE / module_path_text
    if not module_path.is_file():
        raise RuntimeError(f"template module not found: {module_path}")
    module_dir = str(module_path.parent)
    dir_base_text = str(DIR_BASE)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    if dir_base_text not in sys.path:
        sys.path.insert(0, dir_base_text)
    module_name = f"react_agent_flow_template_{template['key'].replace('-', '_')}"
    module_spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"failed to load template module: {module_path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def iter_template_events(template_key: str, context: dict[str, Any]):
    template = get_template_by_key(template_key)
    if template["key"] == "free-talk":
        return []
    module = load_template_module(template["key"])
    if module is None or not hasattr(module, "orchestrator_iter"):
        raise RuntimeError(f"orchestrator_iter is not defined for template: {template['key']}")
    context_next = dict(context)
    context_next["templateKey"] = template["key"]
    return module.orchestrator_iter(context_next)
