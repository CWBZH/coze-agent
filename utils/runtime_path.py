"""Runtime path helpers for source and packaged execution."""

from pathlib import Path
import sys
from typing import Union

from core import settings


def is_frozen() -> bool:
    """Return True when running from a packaged executable."""
    return getattr(sys, "frozen", False)


def get_base_path() -> Path:
    """Return the application base path."""
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[1]


def get_resource_path(relative_path: Union[str, Path]) -> Path:
    """Return an absolute path for a bundled or project resource."""
    base_path = get_base_path()

    if not is_frozen():
        return base_path / relative_path

    if hasattr(sys, "_MEIPASS"):
        resource_dir = Path(sys._MEIPASS)
        resource_path = resource_dir / relative_path
        if resource_path.exists():
            return resource_path

    return base_path / relative_path


def get_temp_path(subpath: Union[str, Path] = "") -> Path:
    """Return the configured runtime data directory path."""
    temp_dir = settings.data_dir()
    if subpath:
        return temp_dir / subpath
    return temp_dir


def ensure_temp_dir(subpath: Union[str, Path] = "") -> Path:
    """Ensure the configured runtime data directory exists."""
    return settings.ensure_dir(get_temp_path(subpath))


def get_config_path(config_name: str = "config.json") -> Path:
    """Return the preferred config file path."""
    exe_dir = get_base_path()
    config_path = exe_dir / config_name

    if not config_path.exists() and not is_frozen():
        config_path = get_resource_path(config_name)

    return config_path


def get_log_path() -> Path:
    """Return the configured app log file path and ensure its directory."""
    settings.ensure_log_dir()
    return settings.log_file_path("app.log")


def get_database_path(db_name: str = "agent.db") -> Path:
    """Return a configured database file path."""
    if db_name == "channel_shop.db":
        settings.ensure_db_parent()
        return settings.db_path()

    db_dir = settings.ensure_data_dir()
    return db_dir / db_name


def get_vector_db_path() -> Path:
    """Return the configured vector database cache directory."""
    return settings.ensure_dir(settings.cache_dir() / "vector_db")


def get_contents_db_path() -> Path:
    """Return the configured contents database file path."""
    settings.ensure_cache_dir()
    return settings.cache_dir() / "contents.db"


def adjust_config_for_runtime(config: dict) -> dict:
    """Adjust config paths for the current runtime."""
    adjusted_config = config.copy()

    if "db_path" in adjusted_config:
        adjusted_config["db_path"] = str(get_database_path())

    if "knowledge_base" in adjusted_config:
        kb_config = adjusted_config["knowledge_base"]

        if "contents_db_path" in kb_config:
            kb_config["contents_db_path"] = str(get_contents_db_path())

        if "vector_db_path" in kb_config:
            kb_config["vector_db_path"] = str(get_vector_db_path())

    path_keys = [
        "log_path",
        "cache_path",
        "data_path",
        "output_path",
    ]

    for key in path_keys:
        if key in adjusted_config:
            path = Path(adjusted_config[key])
            if not path.is_absolute():
                adjusted_config[key] = str(settings.cache_dir() / path.name)

    return adjusted_config


def print_runtime_info():
    """Print runtime path information for manual diagnostics."""
    print("=" * 50)
    print("Runtime path information")
    print("=" * 50)
    print(f"Frozen: {is_frozen()}")
    print(f"Base path: {get_base_path()}")
    print(f"Data dir: {get_temp_path()}")
    print(f"Config file: {get_config_path()}")
    print(f"Log file: {get_log_path()}")
    print(f"Database path: {get_database_path()}")
    print(f"Vector DB path: {get_vector_db_path()}")
    print("=" * 50)


if __name__ == "__main__":
    print_runtime_info()

    print("\nResource path checks:")
    print(f"config.json: {get_resource_path('config.json')}")
    print(f"icon/icon.ico: {get_resource_path('icon/icon.ico')}")
    print(f"app.py: {get_resource_path('app.py')}")

    print("\nPath existence checks:")
    for path in [
        get_resource_path("config.json"),
        get_resource_path("icon/icon.ico"),
        get_temp_path(),
        get_config_path(),
    ]:
        exists = path.exists() if path.is_file() else path.is_dir()
        print(f"{path}: {'exists' if exists else 'missing'}")
