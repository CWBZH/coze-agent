import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_pgvector_smoke.py"
SCHEMA = REPO_ROOT / "deploy" / "sql" / "pgvector_knowledge_chunks.sql"


def test_fake_pgvector_smoke_does_not_connect():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--fake", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok"
    assert payload["connects_pgvector"] is False
    assert payload["schema_applied"] is False
    assert payload["table_available"] is True


def test_schema_path_exists():
    assert SCHEMA.exists()
    assert "CREATE TABLE IF NOT EXISTS knowledge_chunks" in SCHEMA.read_text(encoding="utf-8")


def test_connection_error_masks_dsn_password():
    dsn = "postgresql://user:super-secret-password@127.0.0.1:9/db"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--pg-dsn", dsn, "--check-only", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "error"
    assert payload["connects_pgvector"] is True
    assert "super-secret-password" not in completed.stdout

