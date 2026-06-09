from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _deep_merge(base_value: Any, override_value: Any):
    if isinstance(base_value, dict) and isinstance(override_value, dict):
        merged = dict(base_value)
        for key, value in override_value.items():
            merged[key] = _deep_merge(merged.get(key), value)
        return merged
    return override_value if override_value is not None else base_value


def _safe_load_yaml_file(file_path: Path):
    if not file_path.is_file():
        return {}
    with file_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        return {}
    return data


def load_project_config(dir_base: Path):
    config_dir = dir_base / "config"
    config_default = _safe_load_yaml_file(config_dir / "config.yaml")
    config_local = _safe_load_yaml_file(config_dir / "config.0.yaml")
    merged = _deep_merge(config_default, config_local)
    local_databases = config_local.get("config_databases")
    if isinstance(local_databases, dict) and len(local_databases) > 0:
        merged["config_databases"] = local_databases
    if not isinstance(merged.get("config_databases"), dict):
        merged["config_databases"] = {}
    if not isinstance(merged.get("auth"), dict):
        merged["auth"] = {}
    return merged
