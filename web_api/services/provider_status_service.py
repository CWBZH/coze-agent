from __future__ import annotations

import os
from urllib.parse import urlparse

from web_api.schemas.provider_status import ProviderState, ProviderStatusResponse


PGVECTOR_ENVS = ("AI_WORKFLOW_PGVECTOR_DSN", "WEB_API_PGVECTOR_DSN")
EMBEDDING_PROVIDER_ENV = "WEB_KNOWLEDGE_EMBEDDING_PROVIDER"
DOUBAO_ENVS = ("DOUBAO_EMBEDDING_BASE_URL", "DOUBAO_EMBEDDING_MODEL", "DOUBAO_EMBEDDING_API_KEY")
OLLAMA_ENVS = ("AI_WORKFLOW_OLLAMA_BASE_URL", "AI_WORKFLOW_EMBEDDING_MODEL")
LLM_ENVS = ("AI_WORKFLOW_LLM_BASE_URL", "AI_WORKFLOW_LLM_MODEL", "AI_WORKFLOW_LLM_API_KEY")


class ProviderStatusService:
    """Read provider configuration state without contacting providers."""

    def get_status(self) -> ProviderStatusResponse:
        providers = {
            "pgvector": self._pgvector_status(),
            "embedding": self._embedding_status(),
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
            if state.status in {"config_missing", "invalid_config"} and name in {"pgvector", "embedding", "llm"}
        ]
        return ProviderStatusResponse(engine="internal", no_send=True, providers=providers, warnings=warnings)

    def _pgvector_status(self) -> ProviderState:
        env_name = next((key for key in PGVECTOR_ENVS if os.environ.get(key, "").strip()), PGVECTOR_ENVS[0])
        dsn = os.environ.get(env_name, "").strip()
        if not dsn:
            return ProviderState(configured=False, env_keys_present=[], status="config_missing")
        parsed = urlparse(dsn)
        if parsed.scheme not in {"postgresql", "postgres"} or not parsed.hostname:
            return ProviderState(
                configured=False,
                env_keys_present=[env_name],
                status="invalid_config",
                error_type="invalid_dsn",
            )
        return ProviderState(
            configured=True,
            env_keys_present=[env_name],
            status="configured",
            safe_display={
                "host": parsed.hostname or "",
                "port": str(parsed.port or ""),
                "database": parsed.path.lstrip("/"),
                "username": parsed.username or "",
            },
        )

    def _embedding_provider(self) -> str:
        return os.environ.get(EMBEDDING_PROVIDER_ENV, "doubao").strip().lower() or "doubao"

    def _embedding_status(self) -> ProviderState:
        provider = self._embedding_provider()
        if provider in {"doubao", "ark"}:
            present = [key for key in DOUBAO_ENVS if os.environ.get(key)]
            if len(present) != len(DOUBAO_ENVS):
                return ProviderState(
                    configured=False,
                    env_keys_present=present,
                    status="config_missing",
                    safe_display={"provider": provider},
                )
            return ProviderState(
                configured=True,
                env_keys_present=list(DOUBAO_ENVS),
                status="configured",
                safe_display={
                    "provider": provider,
                    "base_url": "configured",
                    "model": os.environ.get("DOUBAO_EMBEDDING_MODEL", ""),
                },
            )
        if provider == "ollama":
            present = [key for key in OLLAMA_ENVS if os.environ.get(key)]
            if len(present) != len(OLLAMA_ENVS):
                return ProviderState(
                    configured=False,
                    env_keys_present=present,
                    status="config_missing",
                    safe_display={"provider": provider},
                )
            return ProviderState(
                configured=True,
                env_keys_present=list(OLLAMA_ENVS),
                status="configured",
                safe_display={
                    "provider": provider,
                    "base_url": os.environ.get("AI_WORKFLOW_OLLAMA_BASE_URL", ""),
                    "model": os.environ.get("AI_WORKFLOW_EMBEDDING_MODEL", ""),
                },
            )
        return ProviderState(
            configured=False,
            env_keys_present=[EMBEDDING_PROVIDER_ENV] if os.environ.get(EMBEDDING_PROVIDER_ENV) else [],
            status="invalid_config",
            safe_display={"provider": provider},
            error_type="unsupported_embedding_provider",
        )

    def _ollama_status(self) -> ProviderState:
        present = [key for key in OLLAMA_ENVS if os.environ.get(key)]
        if self._embedding_provider() != "ollama" and not present:
            return ProviderState(
                configured=False,
                env_keys_present=[],
                status="disabled",
                safe_display={"state": "not_selected"},
            )
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
