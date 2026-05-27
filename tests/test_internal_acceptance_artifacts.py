import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_acceptance_artifacts.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("internal_acceptance_artifacts", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_creates_artifact_directory_and_all_reports(tmp_path):
    module = _load_module()
    output_dir = tmp_path / "acceptance-run"

    result = module.build_artifacts(output_dir=output_dir, command=["test"], synthetic_limit=1)

    assert output_dir.is_dir()
    assert set(result["files"]) == {
        "manifest.json",
        "synthetic_report.json",
        "dry_run_report.json",
        "comparison_report.json",
        "summary.json",
    }
    for path in result["files"].values():
        assert Path(path).is_file()
        json.loads(Path(path).read_text(encoding="utf-8"))


def test_manifest_is_parseable_and_contains_no_send_fields(tmp_path):
    module = _load_module()
    output_dir = tmp_path / "acceptance-run"

    module.build_artifacts(output_dir=output_dir, command=["artifact-writer"], synthetic_limit=1)

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "acceptance-run"
    assert manifest["backend"] == "internal"
    assert manifest["schema_version"] == module.SCHEMA_VERSION
    assert manifest["command"] == ["artifact-writer"]
    assert manifest["no_send"] is True
    assert manifest["calls_fastgpt"] is False
    assert manifest["calls_llm"] is False
    assert manifest["sends_pdd"] is False
    assert "manifest.json" in manifest["files"]


def test_no_write_returns_path_plan_without_creating_files(tmp_path):
    module = _load_module()
    output_dir = tmp_path / "planned-run"

    result = module.build_artifacts(
        output_dir=output_dir,
        command=["artifact-writer", "--no-write"],
        no_write=True,
        synthetic_limit=1,
    )

    assert result["no_write"] is True
    assert result["output_dir"] == str(output_dir.resolve())
    assert result["files"]["summary.json"] == str(output_dir.resolve() / "summary.json")
    assert not output_dir.exists()


def test_json_artifacts_do_not_contain_forbidden_fields_or_private_content(tmp_path):
    module = _load_module()
    output_dir = tmp_path / "acceptance-run"

    module.build_artifacts(output_dir=output_dir, command=["test"], synthetic_limit=1)

    rendered = "\n".join(path.read_text(encoding="utf-8") for path in output_dir.glob("*.json"))
    forbidden_tokens = {
        '"content"',
        '"reply_text"',
        '"full_reply"',
        '"full_sop"',
        '"sop_records"',
        '"product_details"',
        '"manual_notes"',
        "Compact fake product detail that must stay private",
        "Please ask the buyer to provide clear photos",
    }
    for token in forbidden_tokens:
        assert token not in rendered


def test_output_dir_parameter_is_honored(tmp_path):
    module = _load_module()
    output_dir = tmp_path / "custom" / "internal-artifacts"

    result = module.build_artifacts(output_dir=output_dir, command=["test"], synthetic_limit=1)

    assert result["output_dir"] == str(output_dir.resolve())
    assert (output_dir / "manifest.json").exists()
    assert json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))["run_id"] == "internal-artifacts"


def test_scan_artifact_directory_for_forbidden_fields(tmp_path):
    module = _load_module()
    output_dir = tmp_path / "acceptance-run"
    module.build_artifacts(output_dir=output_dir, command=["test"], synthetic_limit=1)

    assert module.scan_artifact_for_forbidden_fields(output_dir) == []


def test_scan_artifact_reports_forbidden_field_without_value(tmp_path):
    module = _load_module()
    artifact = tmp_path / "bad.json"
    artifact.write_text(
        json.dumps({"case_id": "bad", "token": "SECRET_VALUE_SHOULD_NOT_APPEAR"}),
        encoding="utf-8",
    )

    errors = module.scan_artifact_for_forbidden_fields(artifact)

    assert errors
    assert "token" in errors[0]
    assert "SECRET_VALUE_SHOULD_NOT_APPEAR" not in "\n".join(errors)
