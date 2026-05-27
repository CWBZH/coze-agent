from __future__ import annotations

import os
from urllib.parse import urlparse

from web_api.schemas.provider_status import ProviderState, ProviderStatusResponse


PGVECTOR_ENV = "AI_WORKFLOW_PGVECTOR_DSN"
OLLAMA_ENVS = ("AI_WORKFLOW_OLLAMA_BASE_URL", "AI_WORKFLOW_EMBEDDING_MODEL")
LLM_ENVS = ("AI_WORKFLOW_LLM_BASE_URL", "AI_WORKFLOW_LLM_MODEL", "AI_WORKFLOW_LLM_API_KEY")


class ProviderStatusService:
    """Read provider configuration state without contacting providers."""

    def get_status(self) -> ProviderStatusResponse:
        providers = {
            "pgvector": self._pgvector_status(),
            "ollama": self._ollama_status(),
            "llm": self._llm_status(),
            "pdd_sending": ProviderState(
                configured=False,
                env_keys_present=[],
                status="disabled",
                safe_display={"state": "disabled"},
            ),
        }
        warnings = [
            name
            for name, state in providers.items()
            if state.status in {"config_missing", "invalid_config"} and name != "pdd_sending"
        ]
        return ProviderStatusResponse(engine="internal", no_send=True, providers=providers, warnings=warnings)

    def _pgvector_status(self) -> ProviderState:
        dsn = os.environ.get(PGVECTOR_ENV, "").strip()
        if not dsn:
            return ProviderState(configured=False, env_keys_present=[], status="config_missing")
        parsed = urlparse(dsn)
        if parsed.scheme not in {"postgresql", "postgres"} or not parsed.hostname:
            return ProviderState(
                configured=False,
                env_keys_present=[PGVECTOR_ENV],
                status="invalid_config",
                error_type="invalid_dsn",
            )
        return ProviderState(
            configured=True,
            env_keys_present=[PGVECTOR_ENV],
            status="configured",
            safe_display={
                "host": parsed.hostname or "",
                "port": str(parsed.port or ""),
                "database": parsed.path.lstrip("/"),
                "username": parsed.username or "",
            },
        )

    def _ollama_status(self) -> ProviderState:
        present = [key for key in OLLAMA_ENVS if os.environ.get(key)]
        if len(present) != len(OLLAMA_ENVS):
            return ProviderState(configured=False, env_keys_present=present, status="config_missing")
        return ProviderState(
            configured=True,
            env_keys_present=list(OLLAMA_ENVS),
            status="configured",
            safe_display={
                "base_url": os.environ.get("AI_WORKFLOW_OLLAMA_BASE_URL", ""),
                "model": os.environ.get("AI_WORKFLOW_EMBEDDING_MODEL", ""),
            },
        )

    def _llm_status(self) -> ProviderState:
        present = [key for key in LLM_ENVS if os.environ.get(key)]
        if len(present) != len(LLM_ENVS):
            return ProviderState(configured=False, env_keys_present=present, status="config_missing")
        return ProviderState(
            configured=True,
            env_keys_present=list(LLM_ENVS),
            status="configured",
            safe_display={
                "base_url": "configured",
                "model": os.environ.get("AI_WORKFLOW_LLM_MODEL", ""),
            },
        )
