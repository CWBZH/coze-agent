import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_rag_cleanup.py"


def _run(*args, expected_returncode=0):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    assert completed.returncode == expected_returncode, completed.stderr
    return json.loads(completed.stdout)


def test_fake_cleanup_succeeds_with_safe_defaults():
    payload = _run("--fake", "--json-only")

    assert payload["status"] == "ok"
    assert payload["connects_pgvector"] is False
    assert payload["dry_run"] is True
    assert payload["matched_count"] >= 1


def test_cleanup_rejects_missing_filters():
    payload = _run("--fake", "--source-type-prefix", "", "--namespace", "", "--json-only", expected_returncode=1)

    assert payload["status"] == "rejected"
    assert payload["error_type"] == "unsafe_filters"


def test_real_cleanup_requires_pg_dsn_and_masks_secret():
    payload = _run(
        "--pg-dsn",
        "",
        "--source-type-prefix",
        "pollution_",
        "--namespace",
        "acceptance",
        "--json-only",
        expected_returncode=1,
    )

    assert payload["status"] == "error"
    assert payload["connects_pgvector"] is False


def test_real_cleanup_without_confirm_forces_dry_run():
    payload = _run(
        "--fake",
        "--source-type-prefix",
        "pollution_",
        "--namespace",
        "acceptance",
        "--json-only",
    )

    assert payload["dry_run"] is True
    assert payload["deleted_count"] == 0


def test_fake_legacy_audit_detects_pollution_without_raw_content():
    payload = _run("--fake", "--audit-legacy-pollution", "--json-only")
    rendered = json.dumps(payload, ensure_ascii=False)

    assert payload["status"] == "ok"
    assert payload["connects_pgvector"] is False
    assert payload["legacy_candidate_count"] >= 1
    assert "pollution_old_version" in payload["legacy_source_types"]
    assert "controlled pollution content" not in rendered


def test_legacy_cleanup_dry_run_does_not_delete():
    payload = _run(
        "--fake",
        "--legacy-cleanup",
        "--legacy-source-type-prefix",
        "pollution_",
        "--legacy-version",
        "old-version",
        "--legacy-dry-run",
        "--json-only",
    )

    assert payload["status"] == "ok"
    assert payload["legacy_cleanup"] is True
    assert payload["dry_run"] is True
    assert payload["matched_count"] >= 1
    assert payload["deleted_count"] == 0


def test_legacy_cleanup_confirm_delete_requires_strong_filter():
    payload = _run(
        "--fake",
        "--legacy-cleanup",
        "--legacy-source-type-prefix",
        "pollution_",
        "--legacy-confirm-delete",
        "--json-only",
        expected_returncode=1,
    )

    assert payload["status"] == "rejected"
    assert payload["error_type"] == "unsafe_legacy_filters"


def test_legacy_cleanup_confirm_delete_with_safe_filter_deletes_only_pollution():
    payload = _run(
        "--fake",
        "--legacy-cleanup",
        "--legacy-source-type-prefix",
        "pollution_",
        "--legacy-version",
        "old-version",
        "--legacy-confirm-delete",
        "--json-only",
    )

    assert payload["status"] == "ok"
    assert payload["dry_run"] is False
    assert payload["deleted_count"] >= 1


def test_legacy_cleanup_rejects_non_pollution_prefix():
    payload = _run(
        "--fake",
        "--legacy-cleanup",
        "--legacy-source-type-prefix",
        "sop",
        "--legacy-version",
        "old-version",
        "--legacy-confirm-delete",
        "--json-only",
        expected_returncode=1,
    )

    assert payload["status"] == "rejected"
