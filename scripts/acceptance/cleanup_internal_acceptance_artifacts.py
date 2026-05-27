"""Retention cleanup for internal engine acceptance artifacts."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_DIR = REPO_ROOT / "temp" / "acceptance" / "internal-engine"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean old internal acceptance run-* directories.")
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--keep-last", type=int, default=20)
    parser.add_argument("--max-age-days", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def cleanup_artifacts(
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
    keep_last: int = 20,
    max_age_days: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    resolved_base = base_dir.resolve()
    runs = _list_run_dirs(resolved_base)
    keep_count = max(0, keep_last)
    by_newest = sorted(runs, key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    protected = set(by_newest[:keep_count])
    cutoff = _cutoff(max_age_days)

    delete_candidates = []
    for run_dir in by_newest[keep_count:]:
        if cutoff is None or _mtime(run_dir) < cutoff:
            delete_candidates.append(run_dir)

    deleted = []
    if not dry_run:
        for run_dir in delete_candidates:
            if _is_safe_run_dir(resolved_base, run_dir):
                shutil.rmtree(run_dir)
                deleted.append(str(run_dir))
    else:
        deleted = [str(path) for path in delete_candidates if _is_safe_run_dir(resolved_base, path)]

    return {
        "base_dir": str(resolved_base),
        "scanned": len(runs),
        "kept": len(protected),
        "deleted": deleted,
        "dry_run": dry_run,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = cleanup_artifacts(
        base_dir=args.base_dir,
        keep_last=args.keep_last,
        max_age_days=args.max_age_days,
        dry_run=args.dry_run,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.json_only:
        print(rendered)
    else:
        print("internal_acceptance_cleanup")
        print(rendered)
    return 0


def _list_run_dirs(base_dir: Path) -> list[Path]:
    if not base_dir.exists() or not base_dir.is_dir():
        return []
    return [
        path
        for path in base_dir.iterdir()
        if path.is_dir() and path.name.startswith("run-") and _is_safe_run_dir(base_dir, path)
    ]


def _is_safe_run_dir(base_dir: Path, run_dir: Path) -> bool:
    try:
        resolved_base = base_dir.resolve()
        resolved_run = run_dir.resolve()
    except OSError:
        return False
    return resolved_run.parent == resolved_base and resolved_run.name.startswith("run-")


def _cutoff(max_age_days: int | None) -> datetime | None:
    if max_age_days is None or max_age_days < 0:
        return None
    return datetime.now(timezone.utc) - timedelta(days=max_age_days)


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
