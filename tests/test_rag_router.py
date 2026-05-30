import Session.session_manager  # Import order avoids existing core/logger circular import in tests.

from Message.workflow.fastgpt_engine import FastGPTWorkflowEngine
from Message.workflow.internal_engine import InternalWorkflowEngine
from Message.workflow.rag_retriever import InMemoryRAGRetriever, NullRAGRetriever
import Message.workflow.router as router_module
from Message.workflow.router import create_ai_workflow_engine


class FakeFastGPT:
    pass


def test_router_does_not_enable_rag_by_default(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_BACKEND", "internal")
    monkeypatch.delenv("AI_WORKFLOW_RAG_ENABLED", raising=False)

    engine = create_ai_workflow_engine(fastgpt_handler=FakeFastGPT())

    assert isinstance(engine, InternalWorkflowEngine)
    assert engine.rag_retriever is None


def test_router_fastgpt_ignores_rag_enabled(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_BACKEND", "fastgpt")
    monkeypatch.setenv("AI_WORKFLOW_RAG_ENABLED", "true")
    monkeypatch.setenv("AI_WORKFLOW_VECTOR_STORE", "in_memory")
    monkeypatch.setenv("AI_WORKFLOW_EMBEDDING_PROVIDER", "fake")

    engine = create_ai_workflow_engine(fastgpt_handler=FakeFastGPT())

    assert isinstance(engine, FastGPTWorkflowEngine)


def test_router_internal_rag_enabled_fake_uses_in_memory(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_BACKEND", "internal")
    monkeypatch.setenv("AI_WORKFLOW_RAG_ENABLED", "true")
    monkeypatch.setenv("AI_WORKFLOW_VECTOR_STORE", "in_memory")
    monkeypatch.setenv("AI_WORKFLOW_EMBEDDING_PROVIDER", "fake")

    engine = create_ai_workflow_engine(fastgpt_handler=FakeFastGPT())

    assert isinstance(engine.rag_retriever, InMemoryRAGRetriever)


def test_router_internal_rag_enabled_without_pg_config_is_safe(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_BACKEND", "internal")
    monkeypatch.setenv("AI_WORKFLOW_RAG_ENABLED", "true")
    monkeypatch.setenv("AI_WORKFLOW_VECTOR_STORE", "pgvector")
    monkeypatch.delenv("AI_WORKFLOW_PGVECTOR_DSN", raising=False)

    engine = create_ai_workflow_engine(fastgpt_handler=FakeFastGPT())

    assert isinstance(engine.rag_retriever, NullRAGRetriever)


def test_router_internal_rag_uses_doubao_and_web_pgvector_dsn(monkeypatch):
    class FakePgVectorStore:
        def __init__(self, dsn):
            self.dsn = dsn

    monkeypatch.setattr(router_module, "PgVectorStore", FakePgVectorStore)
    monkeypatch.setenv("AI_WORKFLOW_BACKEND", "internal")
    monkeypatch.setenv("AI_WORKFLOW_RAG_ENABLED", "true")
    monkeypatch.setenv("AI_WORKFLOW_VECTOR_STORE", "pgvector")
    monkeypatch.delenv("AI_WORKFLOW_PGVECTOR_DSN", raising=False)
    monkeypatch.setenv("WEB_API_PGVECTOR_DSN", "postgresql://user:pass@127.0.0.1:5432/db")
    monkeypatch.setenv("WEB_KNOWLEDGE_EMBEDDING_PROVIDER", "doubao")
    monkeypatch.setenv("DOUBAO_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("DOUBAO_EMBEDDING_MODEL", "doubao-embedding-vision-test")

    engine = create_ai_workflow_engine(fastgpt_handler=FakeFastGPT())

    assert engine.rag_retriever is not None
    assert engine.rag_retriever.embedding_client.__class__.__name__ == "DoubaoEmbeddingClient"
    assert engine.rag_retriever.vector_store.dsn == "postgresql://user:pass@127.0.0.1:5432/db"
