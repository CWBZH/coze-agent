"""Lightweight runtime settings.

This module only reads environment variables and safe defaults. It must not
depend on DB, PyQt, ConfigManager, or business modules.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - python-dotenv may be absent in tests
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

if load_dotenv is not None:
    load_dotenv(ENV_FILE, override=False)


def get_str(name: str, default: Optional[str] = None) -> Optional[str]:
    """Return a non-empty environment value, otherwise the provided default."""
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def get_int(name: str, default: int = 0) -> int:
    """Return an integer environment value with a safe fallback."""
    value = get_str(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_bool(name: str, default: bool = False) -> bool:
    """Return a boolean environment value with a safe fallback."""
    value = get_str(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _app_env() -> str:
    return (get_str("APP_ENV", "local") or "local").strip().lower()


def _is_linux_like_env() -> bool:
    return _app_env() in {"linux", "production", "prod"}


def _default_fastgpt_base_url() -> str:
    if _is_linux_like_env():
        return "http://fastgpt:3000/api"
    return "http://localhost:3000/api"


def _default_local_model_base_url() -> str:
    if _is_linux_like_env():
        return "http://ollama:11434"
    return "http://localhost:11434"


def _default_session_compress_base_url() -> str:
    if _is_linux_like_env():
        return "http://ollama-proxy:11435"
    return "http://127.0.0.1:11435"


APP_ENV = _app_env()
FASTGPT_BASE_URL = (get_str("FASTGPT_BASE_URL", _default_fastgpt_base_url()) or "").rstrip("/")
FASTGPT_API_KEY = get_str("FASTGPT_API_KEY", "") or ""
SESSION_COMPRESS_BASE_URL = (
    get_str("SESSION_COMPRESS_BASE_URL", _default_session_compress_base_url()) or ""
).rstrip("/")
SESSION_COMPRESS_API_KEY = get_str("SESSION_COMPRESS_API_KEY", "") or ""
LLM_API_BASE = (get_str("LLM_API_BASE", "https://ark.cn-beijing.volces.com/api/v3") or "").rstrip("/")
LLM_API_KEY = get_str("LLM_API_KEY", "") or ""
LOCAL_MODEL_BASE_URL = (get_str("LOCAL_MODEL_BASE_URL", _default_local_model_base_url()) or "").rstrip("/")


def fastgpt_base_url() -> str:
    return FASTGPT_BASE_URL


def fastgpt_api_key() -> str:
    return FASTGPT_API_KEY


def session_compress_base_url() -> str:
    return SESSION_COMPRESS_BASE_URL


def session_compress_api_key() -> str:
    return SESSION_COMPRESS_API_KEY


def llm_api_base() -> str:
    return LLM_API_BASE


def llm_api_key() -> str:
    return LLM_API_KEY


def local_model_base_url() -> str:
    return LOCAL_MODEL_BASE_URL
