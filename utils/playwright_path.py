from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Optional

from utils.path_utils import get_app_dir


def _playwright_browsers_json() -> Optional[Path]:
    try:
        import playwright

        return Path(playwright.__file__).resolve().parent / "driver" / "package" / "browsers.json"
    except Exception:
        return None


def _required_revisions() -> dict[str, str]:
    browsers_json = _playwright_browsers_json()
    if not browsers_json or not browsers_json.exists():
        return {}

    try:
        data = json.loads(browsers_json.read_text(encoding="utf-8"))
    except Exception:
        return {}

    revisions: dict[str, str] = {}
    for item in data.get("browsers", []):
        name = item.get("name")
        revision = item.get("revision")
        if name and revision:
            revisions[name] = str(revision)
    return revisions


def _has_required_chromium(candidate: Path) -> bool:
    revisions = _required_revisions()
    chromium_revision = revisions.get("chromium")
    headless_revision = revisions.get("chromium-headless-shell")

    if chromium_revision:
        chrome = candidate / f"chromium-{chromium_revision}" / "chrome-win" / "chrome.exe"
        if not chrome.exists():
            return False

    if headless_revision:
        headless = (
            candidate
            / f"chromium_headless_shell-{headless_revision}"
            / "chrome-win"
            / "headless_shell.exe"
        )
        if not headless.exists():
            return False

    return bool(chromium_revision or headless_revision)


def _candidate_paths() -> Iterable[Path]:
    yield get_app_dir() / ".browsers"

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        yield Path(local_app_data) / "ms-playwright"


def configure_playwright_browsers_path() -> Path:
    """Point Playwright at a browser cache matching the installed package.

    The project may contain an older `.browsers` directory. Playwright fails hard
    when `PLAYWRIGHT_BROWSERS_PATH` points at a cache that does not contain the
    exact browser revision required by the installed Python package, so we verify
    the expected revision before setting the environment variable.
    """

    for candidate in _candidate_paths():
        if candidate.exists() and _has_required_chromium(candidate):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(candidate)
            return candidate

    fallback = get_app_dir() / ".browsers"
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(fallback)
    return fallback
