import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_rag_index.py"
SOP_FIXTURE = REPO_ROOT / "docs" / "acceptance" / "fixtures" / "internal_sop_example.md"


def _run(*args):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _run_raw(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


def test_dry_run_fake_indexing_is_metadata_only():
    payload = _run("--shop-id", "synthetic-shop-1", "--sop-file", str(SOP_FIXTURE), "--dry-run", "--json-only")

    assert payload["status"] == "dry_run"
    assert payload["chunk_count"] > 0
    assert payload["embedded_count"] == 0
    assert payload["indexed_count"] == 0
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False
    assert "Please ask the buyer to provide clear photos" not in json.dumps(payload, ensure_ascii=False)


def test_fake_indexing_outputs_summary():
    payload = _run("--shop-id", "synthetic-shop-1", "--sop-file", str(SOP_FIXTURE), "--json-only")

    assert payload["status"] == "ok"
    assert payload["embedded_count"] == payload["chunk_count"]
    assert payload["indexed_count"] == payload["chunk_count"]
    assert payload["embedding_model"] == "bge-m3"


def test_product_fixture_generates_product_chunks_without_details():
    payload = _run(
        "--shop-id",
        "synthetic-shop-1",
        "--product-fixture",
        "--product-version",
        "product-test-v1",
        "--dry-run",
        "--json-only",
    )
    rendered = json.dumps(payload, ensure_ascii=False)

    assert payload["status"] == "dry_run"
    assert payload["product_chunk_count"] > 0
    assert payload["product_version"] == "product-test-v1"
    assert payload["product_domains"] == ["product_catalog"]
    assert "Synthetic ingredient list" not in rendered


def test_real_index_requires_pg_dsn_and_ollama_provider():
    missing_dsn = _run_raw(
        "--shop-id",
        "synthetic-shop-1",
        "--sop-file",
        str(SOP_FIXTURE),
        "--real",
        "--embedding-provider",
        "ollama",
        "--json-only",
    )
    assert missing_dsn.returncode != 0
    assert json.loads(missing_dsn.stdout)["error_type"] == "missing_pg_dsn"

    fake_provider = _run_raw(
        "--shop-id",
        "synthetic-shop-1",
        "--sop-file",
        str(SOP_FIXTURE),
        "--real",
        "--pg-dsn",
        "postgresql://user:secret-password@127.0.0.1/db",
        "--embedding-provider",
        "fake",
        "--json-only",
    )
    assert fake_provider.returncode != 0
    assert "secret-password" not in fake_provider.stdout
    assert json.loads(fake_provider.stdout)["error_type"] == "real_requires_ollama"


def test_pollution_fixture_generates_controlled_chunks_without_content():
    payload = _run(
        "--shop-id",
        "synthetic-shop-1",
        "--sop-file",
        str(SOP_FIXTURE),
        "--pollution-fixture",
        "--pollution-kind",
        "all",
        "--dry-run",
        "--json-only",
    )
    rendered = json.dumps(payload, ensure_ascii=False)

    assert payload["pollution_chunk_count"] == 3
    assert payload["pollution_kind"] == "all"
    assert "old-version" in payload["pollution_versions"]
    assert "after_sales_evidence" in payload["pollution_domains"]
    assert "Synthetic wrong-domain policy pollution" not in rendered


def test_individual_pollution_kinds_are_metadata_only():
    old_version = _run(
        "--shop-id",
        "synthetic-shop-1",
        "--pollution-fixture",
        "--pollution-kind",
        "old_version",
        "--dry-run",
        "--json-only",
    )
    wrong_shop = _run(
        "--shop-id",
        "synthetic-shop-1",
        "--pollution-fixture",
        "--pollution-kind",
        "wrong_shop",
        "--dry-run",
        "--json-only",
    )
    wrong_domain = _run(
        "--shop-id",
        "synthetic-shop-1",
        "--pollution-fixture",
        "--pollution-kind",
        "wrong_domain",
        "--dry-run",
        "--json-only",
    )

    assert old_version["pollution_versions"] == ["old-version"]
    assert old_version["pollution_domains"] == ["logistics_policy"]
    assert wrong_shop["pollution_chunk_count"] == 1
    assert wrong_domain["pollution_domains"] == ["after_sales_evidence"]


def test_index_lifecycle_metadata_summary():
    payload = _run(
        "--shop-id",
        "synthetic-shop-1",
        "--sop-file",
        str(SOP_FIXTURE),
        "--index-run-id",
        "rag-run-test",
        "--namespace",
        "acceptance",
        "--created-by",
        "pytest",
        "--dry-run",
        "--json-only",
    )

    assert payload["index_run_id"] == "rag-run-test"
    assert payload["namespace"] == "acceptance"
    assert payload["is_test_data"] is False


def test_pollution_fixture_marks_test_data():
    payload = _run(
        "--shop-id",
        "synthetic-shop-1",
        "--pollution-fixture",
        "--index-run-id",
        "rag-run-pollution",
        "--dry-run",
        "--json-only",
    )

    assert payload["index_run_id"] == "rag-run-pollution"
    assert payload["pollution_chunk_count"] == 3
    assert payload["pollution_indexed"] is False
    assert payload["pollution_is_test_data"] is True
