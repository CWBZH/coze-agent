import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_rag_embedding_smoke.py"


def test_fake_embedding_smoke_outputs_metadata_only():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--provider", "fake", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok"
    assert payload["provider"] == "fake"
    assert payload["calls_ollama"] is False
    assert payload["vector_hash"]
    assert "synthetic embedding smoke text" not in completed.stdout
    assert "vector" not in payload


def test_ollama_missing_service_returns_sanitized_error():
    secret_text = "SECRET_OLLAMA_TEXT_SHOULD_NOT_LEAK"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--provider",
            "ollama",
            "--base-url",
            "http://127.0.0.1:9",
            "--text",
            secret_text,
            "--timeout",
            "0.1",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "error"
    assert payload["calls_ollama"] is True
    assert secret_text not in completed.stdout

