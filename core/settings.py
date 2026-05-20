"""Lightweight runtime settings.

This module only reads environment variables and safe defaults. It must not
depend on DB, PyQt, ConfigManager, or business modules.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

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


PathValue = Union[str, Path]


def resolve_path(value: PathValue) -> Path:
    """Resolve project-relative paths without creating directories."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def ensure_dir(path: PathValue) -> Path:
    resolved = resolve_path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


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


def _default_redis_host() -> str:
    if _is_linux_like_env():
        return "redis"
    return "localhost"


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

REDIS_HOST = get_str("REDIS_HOST", _default_redis_host()) or _default_redis_host()
REDIS_PORT = get_int("REDIS_PORT", 6379)
REDIS_PASSWORD = get_str("REDIS_PASSWORD", "") or ""
REDIS_DB = get_int("REDIS_DB", 0)

DATA_DIR = resolve_path(get_str("DATA_DIR", "./temp") or "./temp")
LOG_DIR = resolve_path(get_str("LOG_DIR", "./logs") or "./logs")
CACHE_DIR = resolve_path(get_str("CACHE_DIR", str(DATA_DIR / "cache")) or str(DATA_DIR / "cache"))
EXPORT_DIR = resolve_path(get_str("EXPORT_DIR", str(DATA_DIR / "exports")) or str(DATA_DIR / "exports"))
DB_PATH = resolve_path(get_str("DB_PATH", str(DATA_DIR / "channel_shop.db")) or str(DATA_DIR / "channel_shop.db"))
WORKER_STATUS_PATH = resolve_path(
    get_str("WORKER_STATUS_PATH", str(DATA_DIR / "runtime" / "worker_status.json"))
    or str(DATA_DIR / "runtime" / "worker_status.json")
)
BROWSER_CACHE_DIR = resolve_path(get_str("BROWSER_CACHE_DIR", str(BASE_DIR / ".browsers")) or str(BASE_DIR / ".browsers"))
_PLAYWRIGHT_BROWSERS_PATH_VALUE = get_str("PLAYWRIGHT_BROWSERS_PATH")
PLAYWRIGHT_BROWSERS_PATH = (
    resolve_path(_PLAYWRIGHT_BROWSERS_PATH_VALUE)
    if _PLAYWRIGHT_BROWSERS_PATH_VALUE
    else None
)


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


def redis_host() -> str:
    return REDIS_HOST


def redis_port() -> int:
    return REDIS_PORT


def redis_password() -> str:
    return REDIS_PASSWORD


def redis_db() -> int:
    return REDIS_DB


def data_dir() -> Path:
    return DATA_DIR


def log_dir() -> Path:
    return LOG_DIR


def cache_dir() -> Path:
    return CACHE_DIR


def export_dir() -> Path:
    return EXPORT_DIR


def db_path() -> Path:
    return DB_PATH


def worker_status_path() -> Path:
    return WORKER_STATUS_PATH


def ensure_data_dir() -> Path:
    return ensure_dir(DATA_DIR)


def ensure_log_dir() -> Path:
    return ensure_dir(LOG_DIR)


def ensure_cache_dir() -> Path:
    return ensure_dir(CACHE_DIR)


def ensure_export_dir() -> Path:
    return ensure_dir(EXPORT_DIR)


def ensure_db_parent() -> Path:
    return ensure_dir(DB_PATH.parent)


def log_file_path(filename: str = "app.log") -> Path:
    return LOG_DIR / filename


def browser_cache_dir() -> Path:
    return BROWSER_CACHE_DIR


def playwright_browsers_path() -> Optional[Path]:
    return PLAYWRIGHT_BROWSERS_PATH


def project_browsers_dir() -> Path:
    return BASE_DIR / ".browsers"


def windows_playwright_browsers_dir() -> Optional[Path]:
    local_app_data = get_str("LOCALAPPDATA")
    if not local_app_data:
        return None
    return Path(local_app_data).expanduser() / "ms-playwright"
