"""AI workflow backend router."""
from __future__ import annotations

import os
from typing import Optional

from Message.handlers.fastgpt_handler import FastGPTHandler

from .base import AIWorkflowEngine
from .active_version import ActiveVersionResolver
from .answer_generator import OpenAICompatibleAnswerGenerator
from .classifier_factory import IntentClassifierFactoryConfig, create_intent_classifier, get_intent_classifier_name
from .fastgpt_engine import FastGPTWorkflowEngine
from .embedding_client import DoubaoEmbeddingClient, FakeEmbeddingClient, OllamaBgeM3EmbeddingClient
from .internal_engine import InternalWorkflowEngine
from .knowledge_repository import ProductKnowledgeRepository
from .rag_retriever import InMemoryRAGRetriever, NullRAGRetriever, RAGRetriever, VectorStoreRAGRetriever
from .vector_store import PgVectorStore


VALID_BACKENDS = {"fastgpt", "internal"}
DEFAULT_BACKEND = "internal"


def get_ai_workflow_backend(default: str = DEFAULT_BACKEND) -> str:
    backend = (os.getenv("AI_WORKFLOW_BACKEND") or default or DEFAULT_BACKEND).strip().lower()
    if backend not in VALID_BACKENDS:
        return DEFAULT_BACKEND
    return backend


def create_ai_workflow_engine(
    backend: Optional[str] = None,
    fastgpt_handler: Optional[FastGPTHandler] = None,
    rag_retriever: Optional[RAGRetriever] = None,
) -> AIWorkflowEngine:
    selected = get_ai_workflow_backend() if backend is None else backend.strip().lower()
    if selected == "internal":
        return InternalWorkflowEngine(
            knowledge_repository=ProductKnowledgeRepository(),
            intent_classifier=create_intent_classifier(
                IntentClassifierFactoryConfig(
                    classifier=get_intent_classifier_name(),
                    backend="internal",
                    base_url=os.getenv("AI_WORKFLOW_LLM_BASE_URL") or "",
                    model=os.getenv("AI_WORKFLOW_LLM_MODEL") or "intent-classifier",
                    api_key_env=os.getenv("AI_WORKFLOW_LLM_API_KEY_ENV") or "AI_WORKFLOW_LLM_API_KEY",
                    timeout_seconds=_float_env("AI_WORKFLOW_LLM_TIMEOUT_SECONDS", 20.0),
                )
            ),
            answer_generator=create_answer_generator_for_backend(selected),
            rag_retriever=rag_retriever if rag_retriever is not None else create_rag_retriever_for_backend(selected),
            active_version_resolver=ActiveVersionResolver(),
        )
    return FastGPTWorkflowEngine(fastgpt_handler)


def create_answer_generator_for_backend(backend: str):
    if str(backend or "").strip().lower() != "internal":
        return None
    generator = _answer_generator_name()
    if generator not in {"openai_compatible", "real", "llm"}:
        return None
    return OpenAICompatibleAnswerGenerator(
        base_url=os.getenv("AI_WORKFLOW_LLM_BASE_URL") or "",
        model=os.getenv("AI_WORKFLOW_LLM_MODEL") or "",
        api_key_env=os.getenv("AI_WORKFLOW_LLM_API_KEY_ENV") or "AI_WORKFLOW_LLM_API_KEY",
        timeout_seconds=_float_env("AI_WORKFLOW_LLM_TIMEOUT_SECONDS", 20.0),
    )


def create_rag_retriever_for_backend(backend: str) -> RAGRetriever | None:
    if str(backend or "").strip().lower() != "internal":
        return None
    if not _truthy(os.getenv("AI_WORKFLOW_RAG_ENABLED")):
        return None

    vector_store_name = (os.getenv("AI_WORKFLOW_VECTOR_STORE") or "pgvector").strip().lower()
    embedding_provider = _embedding_provider_name()
    embedding_model = _embedding_model_name(embedding_provider)
    dimension = _int_env("AI_WORKFLOW_EMBEDDING_DIMENSION", 1024)

    if vector_store_name in {"fake", "in_memory", "memory"} or embedding_provider == "fake":
        return InMemoryRAGRetriever(
            embedding_client=FakeEmbeddingClient(dimension=dimension, model=embedding_model),
        )

    if vector_store_name != "pgvector":
        return NullRAGRetriever(status="disabled_invalid_config")

    dsn = (os.getenv("AI_WORKFLOW_PGVECTOR_DSN") or os.getenv("WEB_API_PGVECTOR_DSN") or "").strip()
    if not dsn:
        return NullRAGRetriever(status="disabled_missing_pgvector_dsn")

    if embedding_provider in {"doubao", "ark", "volcengine"}:
        if not embedding_model:
            return NullRAGRetriever(status="disabled_missing_doubao_embedding_model")
        api_key = (
            os.getenv("DOUBAO_EMBEDDING_API_KEY")
            or os.getenv("ARK_EMBEDDING_API_KEY")
            or os.getenv("ARK_API_KEY")
            or ""
        ).strip()
        if not api_key:
            return NullRAGRetriever(status="disabled_missing_doubao_embedding_api_key")
        return VectorStoreRAGRetriever(
            embedding_client=DoubaoEmbeddingClient(
                base_url=(
                    os.getenv("DOUBAO_EMBEDDING_BASE_URL")
                    or os.getenv("ARK_EMBEDDING_BASE_URL")
                    or os.getenv("ARK_BASE_URL")
                    or "https://ark.cn-beijing.volces.com/api/v3"
                ),
                api_key=api_key,
                model=embedding_model,
                endpoint=os.getenv("DOUBAO_EMBEDDING_ENDPOINT") or os.getenv("ARK_EMBEDDING_ENDPOINT") or "auto",
                timeout=_float_env("AI_WORKFLOW_EMBEDDING_TIMEOUT_SECONDS", 20.0),
            ),
            vector_store=PgVectorStore(dsn),
        )

    if embedding_provider != "ollama":
        return NullRAGRetriever(status="disabled_invalid_embedding_provider")

    return VectorStoreRAGRetriever(
        embedding_client=OllamaBgeM3EmbeddingClient(
            base_url=os.getenv("AI_WORKFLOW_OLLAMA_BASE_URL") or "http://localhost:11434",
            model=embedding_model,
        ),
        vector_store=PgVectorStore(dsn),
    )


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _answer_generator_name() -> str:
    configured = (os.getenv("AI_WORKFLOW_ANSWER_GENERATOR") or "").strip().lower()
    if configured:
        return configured
    if _truthy(os.getenv("AI_WORKFLOW_USE_REAL_ANSWER_GENERATOR")):
        return "openai_compatible"
    return "null"


def _embedding_provider_name() -> str:
    configured = (
        os.getenv("AI_WORKFLOW_EMBEDDING_PROVIDER")
        or os.getenv("WEB_KNOWLEDGE_EMBEDDING_PROVIDER")
        or ""
    ).strip().lower()
    if configured:
        return configured
    if os.getenv("DOUBAO_EMBEDDING_API_KEY") or os.getenv("ARK_EMBEDDING_API_KEY") or os.getenv("ARK_API_KEY"):
        return "doubao"
    return "ollama"


def _embedding_model_name(provider: str) -> str:
    if provider in {"doubao", "ark", "volcengine"}:
        return (
            os.getenv("AI_WORKFLOW_EMBEDDING_MODEL")
            or os.getenv("DOUBAO_EMBEDDING_MODEL")
            or os.getenv("ARK_EMBEDDING_MODEL")
            or ""
        ).strip()
    return (os.getenv("AI_WORKFLOW_EMBEDDING_MODEL") or "bge-m3").strip()


def _int_env(name: str, default: int) -> int:
    try:
        value = int(str(os.getenv(name) or "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _float_env(name: str, default: float) -> float:
    try:
        value = float(str(os.getenv(name) or "").strip())
    except ValueError:
        return default
    return value if value > 0 else default
