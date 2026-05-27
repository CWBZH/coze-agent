from pathlib import Path

from scripts.acceptance.cleanup_internal_acceptance_artifacts import cleanup_artifacts


def _run_dir(base: Path, name: str) -> Path:
    path = base / name
    path.mkdir(parents=True)
    (path / "summary.json").write_text("{}", encoding="utf-8")
    return path


def test_cleanup_keeps_last_n_run_dirs(tmp_path):
    base = tmp_path / "internal-engine"
    old = _run_dir(base, "run-20260101-000000")
    new = _run_dir(base, "run-20260102-000000")

    result = cleanup_artifacts(base_dir=base, keep_last=1, dry_run=False)

    assert result["scanned"] == 2
    assert result["kept"] == 1
    assert old.exists() is False
    assert new.exists() is True


def test_cleanup_dry_run_deletes_nothing(tmp_path):
    base = tmp_path / "internal-engine"
    old = _run_dir(base, "run-20260101-000000")
    _run_dir(base, "run-20260102-000000")

    result = cleanup_artifacts(base_dir=base, keep_last=1, dry_run=True)

    assert old.exists() is True
    assert result["deleted"]
    assert result["dry_run"] is True


def test_cleanup_ignores_non_run_directories(tmp_path):
    base = tmp_path / "internal-engine"
    keep = base / "manual"
    keep.mkdir(parents=True)
    _run_dir(base, "run-20260101-000000")

    cleanup_artifacts(base_dir=base, keep_last=0, dry_run=False)

    assert keep.exists() is True


def test_cleanup_missing_base_is_empty(tmp_path):
    result = cleanup_artifacts(base_dir=tmp_path / "missing", keep_last=20, dry_run=False)

    assert result["scanned"] == 0
    assert result["deleted"] == []
