from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml

CURRENT_DIR = Path(__file__).resolve().parent
DIR_BASE = Path(os.environ.get("DIR_BASE", str(CURRENT_DIR.parent))).resolve()
CONFIG_DIR = DIR_BASE / "config"
if str(CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(CONFIG_DIR))

from config_loader import load_project_config

DEFAULT_PORT = 9410


def get_dir_base():
    return DIR_BASE


def get_project_config():
    return load_project_config(DIR_BASE)


def normalize_database_config(item_key: str, raw_item: dict[str, Any]):
    return {
        "key": str(item_key or "").strip() or "default",
        "label": str(raw_item.get("label") or raw_item.get("name") or item_key or "default").strip(),
        "host": str(raw_item.get("ip") or raw_item.get("host") or "127.0.0.1").strip(),
        "port": int(raw_item.get("port") or 5432),
        "databaseName": str(raw_item.get("database_name") or raw_item.get("databaseName") or "postgres").strip(),
        "username": str(raw_item.get("username") or "postgres").strip(),
        "password": str(raw_item.get("password") or "postgres"),
    }


def load_database_config():
    project_config = get_project_config()
    raw_databases = project_config.get("config_databases") or {}
    if not isinstance(raw_databases, dict) or not raw_databases:
        return normalize_database_config("default", {})
    first_key = list(raw_databases.keys())[0]
    first_item = raw_databases[first_key]
    if not isinstance(first_item, dict):
        return normalize_database_config("default", {})
    return normalize_database_config(str(first_key), first_item)


def load_content_type_config():
    config_path = CONFIG_DIR / "conversation_content_type.yaml"
    if not config_path.is_file():
        return {"contentTypeByCode": {}}
    with config_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        return {"contentTypeByCode": {}}
    content_type_by_code = data.get("contentTypeByCode")
    if not isinstance(content_type_by_code, dict):
        data["contentTypeByCode"] = {}
    return data


def get_model_service_config():
    project_config = get_project_config()
    return {
        "providerName": str(project_config.get("llm_provider") or "google"),
        "apiKey": str(project_config.get("google_api_key") or os.environ.get("GOOGLE_API_KEY") or ""),
        "modelName": str(project_config.get("google_model") or "gemini-2.5-flash"),
    }


def get_google_model_config():
    config_data = get_model_service_config()
    return {
        "apiKey": config_data["apiKey"],
        "model": config_data["modelName"],
    }
