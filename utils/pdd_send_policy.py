from __future__ import annotations

import os


TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}


def is_pdd_sending_enabled() -> bool:
    return os.getenv("PDD_SENDING_ENABLED", "false").strip().lower() in TRUE_VALUES


def pdd_sending_status() -> str:
    return "enabled" if is_pdd_sending_enabled() else "disabled"
