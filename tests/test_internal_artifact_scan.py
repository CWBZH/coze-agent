import json
from pathlib import Path

from scripts.acceptance.internal_acceptance_artifacts import scan_artifact_for_forbidden_fields


def test_scan_single_json_file_passes_for_metadata_only(tmp_path):
    artifact = tmp_path / "report.json"
    artifact.write_text(json.dumps({"case_id": "c1", "content_hash": "abc"}), encoding="utf-8")

    assert scan_artifact_for_forbidden_fields(artifact) == []


def test_scan_directory_reports_forbidden_raw_fields(tmp_path):
    good = tmp_path / "good.json"
    bad = tmp_path / "bad.json"
    good.write_text(json.dumps({"case_id": "c1"}), encoding="utf-8")
    bad.write_text(json.dumps({"results": [{"reply_text": "secret reply body"}]}), encoding="utf-8")

    errors = scan_artifact_for_forbidden_fields(tmp_path)

    rendered = "\n".join(errors)
    assert "bad.json" in rendered
    assert "reply_text" in rendered
    assert "secret reply body" not in rendered


def test_scan_invalid_json_reports_file_only(tmp_path):
    artifact = tmp_path / "bad.json"
    artifact.write_text("{not-json", encoding="utf-8")

    errors = scan_artifact_for_forbidden_fields(artifact)

    assert errors == ["bad.json: invalid JSON"]


def test_scan_missing_path_returns_error():
    errors = scan_artifact_for_forbidden_fields(Path("missing-internal-artifact.json"))

    assert errors
    assert "does not exist" in errors[0]
