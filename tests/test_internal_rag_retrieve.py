import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_rag_retrieve.py"
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


def test_retrieve_filters_domain_and_hides_content():
    payload = _run(
        "--shop-id",
        "synthetic-shop-1",
        "--domain",
        "logistics_policy",
        "--query",
        "为什么还没到",
        "--sop-file",
        str(SOP_FIXTURE),
        "--json-only",
    )

    assert payload["status"] == "ok"
    assert payload["hit_count"] >= 1
    assert all(hit["domain"] == "logistics_policy" for hit in payload["hits"])
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "Please ask the buyer to provide clear photos" not in rendered
    assert "content" not in payload["hits"][0]


def test_real_retrieve_requires_pg_dsn_and_ollama_provider():
    missing_dsn = _run_raw(
        "--shop-id",
        "synthetic-shop-1",
        "--domain",
        "logistics_policy",
        "--query",
        "why",
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
        "--domain",
        "logistics_policy",
        "--query",
        "why",
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
