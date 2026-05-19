from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Optional

from core import settings


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
        chrome_root = candidate / f"chromium-{chromium_revision}"
        chrome_candidates = [
            chrome_root / "chrome-win" / "chrome.exe",
            chrome_root / "chrome-linux" / "chrome",
            chrome_root / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
        ]
        if not any(path.exists() for path in chrome_candidates):
            return False

    if headless_revision:
        headless_root = candidate / f"chromium_headless_shell-{headless_revision}"
        headless_candidates = [
            headless_root / "chrome-win" / "headless_shell.exe",
            headless_root / "chrome-linux" / "headless_shell",
            headless_root / "chrome-mac" / "headless_shell",
        ]
        if not any(path.exists() for path in headless_candidates):
            return False

    return bool(chromium_revision or headless_revision)


def _candidate_paths() -> Iterable[Path]:
    seen: set[Path] = set()

    configured = settings.playwright_browsers_path()
    if configured:
        resolved = configured.resolve()
        seen.add(resolved)
        yield configured

    cache_dir = settings.browser_cache_dir()
    resolved_cache = cache_dir.resolve()
    if resolved_cache not in seen:
        seen.add(resolved_cache)
        yield cache_dir

    project_dir = settings.project_browsers_dir()
    resolved_project = project_dir.resolve()
    if resolved_project not in seen:
        seen.add(resolved_project)
        yield project_dir

    windows_dir = settings.windows_playwright_browsers_dir()
    if windows_dir:
        resolved_windows = windows_dir.resolve()
        if resolved_windows not in seen:
            yield windows_dir


def configure_playwright_browsers_path() -> Path:
    """Point Playwright at a browser cache matching the installed package.

    The project may contain an older `.browsers` directory. Playwright fails hard
    when `PLAYWRIGHT_BROWSERS_PATH` points at a cache that does not contain the
    exact browser revision required by the installed Python package, so we verify
    the expected revision before setting the environment variable.
    """

    configured = settings.playwright_browsers_path()
    if configured:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(configured)
        return configured

    if os.getenv("BROWSER_CACHE_DIR"):
        cache_dir = settings.browser_cache_dir()
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(cache_dir)
        return cache_dir

    for candidate in _candidate_paths():
        if candidate.exists() and _has_required_chromium(candidate):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(candidate)
            return candidate

    fallback = settings.project_browsers_dir()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(fallback)
    return fallback
