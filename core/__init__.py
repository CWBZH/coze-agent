"""
Core infrastructure exports.

Keep this module lightweight: logger setup imports ``from core import settings``,
so importing dependency-injection modules here eagerly creates a circular import.
"""

from . import settings as settings

__all__ = [
    "settings",
    "DIContainer",
    "container",
    "configure_standard_services",
    "MemoryCache",
    "BaseService",
    "ConnectionStatusManager",
    "ConnectionState",
    "ConnectionStatus",
]


def __getattr__(name: str):
    if name in {"DIContainer", "container", "configure_standard_services"}:
        from .di_container import DIContainer, configure_standard_services, container

        exports = {
            "DIContainer": DIContainer,
            "container": container,
            "configure_standard_services": configure_standard_services,
        }
        return exports[name]
    if name == "MemoryCache":
        from .cache import MemoryCache

        return MemoryCache
    if name == "BaseService":
        from .base_service import BaseService

        return BaseService
    if name in {"ConnectionStatusManager", "ConnectionState", "ConnectionStatus"}:
        from .connection_status import ConnectionState, ConnectionStatus, ConnectionStatusManager

        exports = {
            "ConnectionStatusManager": ConnectionStatusManager,
            "ConnectionState": ConnectionState,
            "ConnectionStatus": ConnectionStatus,
        }
        return exports[name]
    raise AttributeError(f"module 'core' has no attribute {name!r}")
