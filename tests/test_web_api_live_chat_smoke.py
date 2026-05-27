import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from web_api.deps import get_live_chat_service
from web_api.main import app
from web_api.services.live_chat_service import LiveChatService
from web_api.services.internal_engine_adapter import WebEngineAttempt
from web_api.services.trace_service import TraceService


REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "web_admin_live_chat_smoke.py"


def _client() -> TestClient:
    service = LiveChatService(trace_service=TraceService())
    app.dependency_overrides[get_live_chat_service] = lambda: service
    return TestClient(app)


def _send(profile: str, body: dict | None = None):
    client = _client()
    session = client.post("/api/live-chat/sessions", json={"shop_id": "323473738"}).json()
    payload = {
        "shop_id": "323473738",
        "message": "这个多少钱",
        "smoke_profile": profile,
        "no_send": True,
    }
    payload.update(body or {})
    return client.post(f"/api/live-chat/sessions/{session['session_id']}/messages", json=payload)


def test_facade_smoke_profile_reports_provider_and_stage_status():
    response = _send("facade", {"use_real_engine": False})

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["smoke_profile"] == "facade"
    assert trace["engine_mode"] == "facade"
    assert trace["provider_status"]["real_engine"] == "skipped"
    assert trace["provider_status"]["pgvector"] == "disabled"
    assert trace["provider_status"]["ollama"] == "disabled"
    assert trace["provider_status"]["llm"] == "disabled"
    assert trace["stage_status"]["context"] == "ok"
    assert "total" in trace["latency_ms"]
    assert trace["sends_pdd"] is False
    assert "fastgpt" not in response.text.lower()


def test_real_engine_only_profile_calls_adapter_without_external_providers():
    response = _send(
        "real_engine_only",
        {
            "use_real_engine": True,
            "use_real_pgvector": False,
            "use_real_ollama": False,
            "use_real_llm": False,
            "use_real_intent_classifier": False,
            "use_real_answer_generator": False,
        },
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["smoke_profile"] == "real_engine_only"
    assert trace["engine_mode"] == "real_internal"
    assert trace["real_engine_called"] is True
    assert trace["provider_status"]["real_engine"] == "ok"
    assert trace["calls_llm"] is False
    assert trace["calls_ollama"] is False
    assert trace["connects_pgvector"] is False
    assert trace["sends_pdd"] is False


def test_real_full_profile_does_not_expand_to_real_provider_flags_in_schema():
    calls = {}

    class CapturingAdapter:
        def run_message(self, *, session_id, payload, session_state, product_context, product_anchor_source):
            del session_id, session_state, product_context, product_anchor_source
            calls["flags"] = {
                "use_real_engine": payload.use_real_engine,
                "use_real_pgvector": payload.use_real_pgvector,
                "use_real_ollama": payload.use_real_ollama,
                "use_real_llm": payload.use_real_llm,
                "use_real_intent_classifier": payload.use_real_intent_classifier,
                "use_real_answer_generator": payload.use_real_answer_generator,
            }
            return WebEngineAttempt(
                trace_patch={
                    "smoke_profile": payload.smoke_profile,
                    "engine_mode": "captured",
                    "engine_adapter_status": "captured",
                    "real_engine_called": False,
                    "sends_pdd": False,
                    "no_send": True,
                }
            )

    service = LiveChatService(trace_service=TraceService(), engine_adapter=CapturingAdapter())
    app.dependency_overrides[get_live_chat_service] = lambda: service
    client = TestClient(app)
    session = client.post("/api/live-chat/sessions", json={"shop_id": "323473738"}).json()

    response = client.post(
        f"/api/live-chat/sessions/{session['session_id']}/messages",
        json={"shop_id": "323473738", "message": "这个多少钱", "smoke_profile": "real_full", "no_send": True},
    )

    assert response.status_code == 200
    assert calls["flags"] == {
        "use_real_engine": False,
        "use_real_pgvector": False,
        "use_real_ollama": False,
        "use_real_llm": False,
        "use_real_intent_classifier": False,
        "use_real_answer_generator": False,
    }


def test_real_rag_profile_missing_environment_is_config_missing(monkeypatch):
    for key in ("AI_WORKFLOW_PGVECTOR_DSN", "AI_WORKFLOW_OLLAMA_BASE_URL", "AI_WORKFLOW_EMBEDDING_MODEL"):
        monkeypatch.delenv(key, raising=False)

    response = _send(
        "real_rag",
        {
            "use_real_engine": True,
            "use_real_pgvector": True,
            "use_real_ollama": True,
            "use_real_llm": False,
        },
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["smoke_profile"] == "real_rag"
    assert trace["engine_adapter_status"] == "config_missing"
    assert trace["provider_status"]["pgvector"] == "config_missing"
    assert trace["provider_status"]["ollama"] == "config_missing"
    assert trace["connects_pgvector"] is False
    assert trace["calls_ollama"] is False
    assert trace["sends_pdd"] is False
    assert "postgresql://" not in response.text


def test_real_llm_profiles_missing_environment_are_config_missing(monkeypatch):
    for key in ("AI_WORKFLOW_LLM_BASE_URL", "AI_WORKFLOW_LLM_MODEL", "AI_WORKFLOW_LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    for profile, flags in {
        "real_intent": {"use_real_intent_classifier": True, "use_real_answer_generator": False},
        "real_answer": {"use_real_intent_classifier": False, "use_real_answer_generator": True},
        "real_full": {"use_real_pgvector": True, "use_real_ollama": True, "use_real_intent_classifier": True, "use_real_answer_generator": True},
    }.items():
        response = _send(
            profile,
            {
                "use_real_engine": True,
                "use_real_llm": True,
                **flags,
            },
        )
        assert response.status_code == 200
        trace = response.json()["trace"]
        assert trace["engine_adapter_status"] == "config_missing"
        assert trace["provider_status"]["llm"] == "config_missing"
        assert trace["calls_llm"] is False
        assert trace["sends_pdd"] is False
        assert "authorization:" not in response.text.lower()
        assert "ark-" not in response.text.lower()


def test_smoke_script_provider_status_outputs_config_state_without_secrets():
    completed = subprocess.run(
        [sys.executable, str(SMOKE_SCRIPT), "--provider-status", "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert completed.returncode == 0
    assert '"provider_status"' in completed.stdout
    assert '"engine": "internal"' in completed.stdout
    assert "postgresql://" not in completed.stdout
    assert "ark-" not in completed.stdout.lower()
    assert "authorization:" not in completed.stdout.lower()


def test_smoke_script_require_real_providers_fails_when_env_missing():
    env = os.environ.copy()
    for key in (
        "AI_WORKFLOW_PGVECTOR_DSN",
        "AI_WORKFLOW_OLLAMA_BASE_URL",
        "AI_WORKFLOW_EMBEDDING_MODEL",
        "AI_WORKFLOW_LLM_BASE_URL",
        "AI_WORKFLOW_LLM_MODEL",
        "AI_WORKFLOW_LLM_API_KEY",
    ):
        env.pop(key, None)
    completed = subprocess.run(
        [
            sys.executable,
            str(SMOKE_SCRIPT),
            "--profile",
            "real_full",
            "--real-providers",
            "--require-real-providers",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert completed.returncode == 1
    assert "provider_config_missing" in completed.stdout
    assert "missing_providers" in completed.stdout
    assert "postgresql://" not in completed.stdout
    assert "ark-" not in completed.stdout.lower()
