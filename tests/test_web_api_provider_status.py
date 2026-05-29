from fastapi.testclient import TestClient

from web_api.main import app


def _client() -> TestClient:
    return TestClient(app)


def test_provider_status_missing_environment_is_config_missing(monkeypatch):
    for key in (
        "AI_WORKFLOW_PGVECTOR_DSN",
        "WEB_API_PGVECTOR_DSN",
        "WEB_KNOWLEDGE_EMBEDDING_PROVIDER",
        "DOUBAO_EMBEDDING_BASE_URL",
        "DOUBAO_EMBEDDING_MODEL",
        "DOUBAO_EMBEDDING_API_KEY",
        "AI_WORKFLOW_OLLAMA_BASE_URL",
        "AI_WORKFLOW_EMBEDDING_MODEL",
        "AI_WORKFLOW_LLM_BASE_URL",
        "AI_WORKFLOW_LLM_MODEL",
        "AI_WORKFLOW_LLM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    response = _client().get("/api/provider-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["engine"] == "internal"
    assert payload["no_send"] is True
    assert payload["providers"]["pgvector"]["status"] == "config_missing"
    assert payload["providers"]["embedding"]["status"] == "config_missing"
    assert payload["providers"]["ollama"]["status"] == "disabled"
    assert payload["providers"]["llm"]["status"] == "config_missing"
    assert payload["providers"]["pdd_sending"]["status"] == "disabled"
    assert "fastgpt" not in response.text.lower()


def test_provider_status_configured_doubao_environment_returns_safe_summary(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_PGVECTOR_DSN", "postgresql://postgres:super-secret@localhost:5433/internaldb")
    monkeypatch.setenv("WEB_KNOWLEDGE_EMBEDDING_PROVIDER", "doubao")
    monkeypatch.setenv("DOUBAO_EMBEDDING_BASE_URL", "https://ark.example.test/api/v3")
    monkeypatch.setenv("DOUBAO_EMBEDDING_MODEL", "doubao-embedding-test")
    monkeypatch.setenv("DOUBAO_EMBEDDING_API_KEY", "doubao-secret-value")
    monkeypatch.delenv("AI_WORKFLOW_OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("AI_WORKFLOW_EMBEDDING_MODEL", raising=False)
    monkeypatch.setenv("AI_WORKFLOW_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("AI_WORKFLOW_LLM_MODEL", "test-model")
    monkeypatch.setenv("AI_WORKFLOW_LLM_API_KEY", "ark-test-secret-value")

    response = _client().get("/api/provider-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["providers"]["pgvector"]["status"] == "configured"
    assert payload["providers"]["pgvector"]["safe_display"] == {
        "host": "localhost",
        "port": "5433",
        "database": "internaldb",
        "username": "postgres",
    }
    assert payload["providers"]["embedding"]["status"] == "configured"
    assert payload["providers"]["embedding"]["safe_display"]["provider"] == "doubao"
    assert payload["providers"]["embedding"]["safe_display"]["model"] == "doubao-embedding-test"
    assert payload["providers"]["ollama"]["status"] == "disabled"
    assert payload["providers"]["llm"]["status"] == "configured"
    assert payload["providers"]["llm"]["safe_display"]["base_url"] == "configured"
    assert payload["providers"]["llm"]["safe_display"]["model"] == "test-model"
    assert "ollama" not in payload["warnings"]
    assert "super-secret" not in response.text
    assert "doubao-secret-value" not in response.text
    assert "postgresql://" not in response.text
    assert "ark-test-secret-value" not in response.text
    assert "authorization" not in response.text.lower()
    assert "fastgpt" not in response.text.lower()


def test_provider_status_configured_ollama_embedding_returns_safe_summary(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_PGVECTOR_DSN", "postgresql://postgres:super-secret@localhost:5433/internaldb")
    monkeypatch.setenv("WEB_KNOWLEDGE_EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setenv("AI_WORKFLOW_OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("AI_WORKFLOW_EMBEDDING_MODEL", "bge-m3")
    monkeypatch.setenv("AI_WORKFLOW_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("AI_WORKFLOW_LLM_MODEL", "test-model")
    monkeypatch.setenv("AI_WORKFLOW_LLM_API_KEY", "ark-test-secret-value")

    response = _client().get("/api/provider-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["providers"]["embedding"]["status"] == "configured"
    assert payload["providers"]["embedding"]["safe_display"]["provider"] == "ollama"
    assert payload["providers"]["embedding"]["safe_display"]["model"] == "bge-m3"
    assert payload["providers"]["ollama"]["status"] == "configured"
    assert payload["providers"]["ollama"]["safe_display"]["model"] == "bge-m3"
    assert "super-secret" not in response.text
    assert "ark-test-secret-value" not in response.text


def test_provider_status_invalid_pgvector_dsn_is_sanitized(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_PGVECTOR_DSN", "not a postgres dsn with password secret-value")
    monkeypatch.delenv("WEB_KNOWLEDGE_EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("DOUBAO_EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("DOUBAO_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("DOUBAO_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("AI_WORKFLOW_OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("AI_WORKFLOW_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("AI_WORKFLOW_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("AI_WORKFLOW_LLM_MODEL", raising=False)
    monkeypatch.delenv("AI_WORKFLOW_LLM_API_KEY", raising=False)

    response = _client().get("/api/provider-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["providers"]["pgvector"]["status"] == "invalid_config"
    assert payload["providers"]["pgvector"]["error_type"] == "invalid_dsn"
    assert "secret-value" not in response.text
