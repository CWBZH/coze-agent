import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_live_chat.py"


def _run_live_chat(*args, env=None, expected_returncode=0):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env={**os.environ, **(env or {})},
    )
    assert completed.returncode == expected_returncode, completed.stderr
    return completed.stdout


def test_check_config_requires_explicit_real_service_args():
    stdout = _run_live_chat(
        "--shop-id",
        "synthetic-shop-1",
        "--check-config",
        "--json-only",
        expected_returncode=1,
    )
    payload = json.loads(stdout)

    assert payload["status"] == "error"
    assert payload["error_type"] == "missing_required_args"
    assert payload["no_send"] is True
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False
    assert payload["calls_fastgpt"] is False
    assert payload["sends_pdd"] is False


def test_check_config_is_no_send_and_does_not_echo_secrets():
    stdout = _run_live_chat(
        "--shop-id",
        "synthetic-shop-1",
        "--pg-dsn",
        "postgresql://user:secret-password@localhost:5432/db",
        "--ollama-base-url",
        "http://localhost:11434",
        "--embedding-model",
        "bge-m3",
        "--llm-base-url",
        "http://localhost:11435",
        "--llm-model",
        "doubao-seed-2-0-mini-260215",
        "--llm-api-key-env",
        "AI_WORKFLOW_TEST_LIVE_CHAT_KEY",
        "--check-config",
        "--json-only",
        env={"AI_WORKFLOW_TEST_LIVE_CHAT_KEY": "live-chat-secret-key"},
    )
    payload = json.loads(stdout)

    assert payload["status"] == "ok"
    assert payload["no_send"] is True
    assert payload["calls_llm"] is False
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False
    assert payload["calls_fastgpt"] is False
    assert payload["sends_pdd"] is False
    assert payload["product_version"] == "real-product-v1"
    assert payload["sop_version"] == "sop-test-v1"
    assert payload["rag_top_k"] == 3
    assert payload["history_window"] == 6
    assert "secret-password" not in stdout
    assert "postgresql://" not in stdout
    assert "live-chat-secret-key" not in stdout
