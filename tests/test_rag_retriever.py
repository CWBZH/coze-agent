import Session.session_manager  # Import order avoids existing core/logger circular import in tests.

from Message.workflow.embedding_client import EmbeddingVector
from Message.workflow.rag_retriever import InMemoryRAGRetriever, NullRAGRetriever, VectorStoreRAGRetriever
from Message.workflow.rag_types import KnowledgeChunk
from Message.workflow.vector_store import InMemoryVectorStore
from Message.workflow.types import WorkflowContext


def _context(shop_id="shop-a", content="shipping question") -> WorkflowContext:
    return WorkflowContext(
        trace_id="trace-rag",
        shop_id=shop_id,
        user_id="user-a",
        buyer_id="buyer-a",
        session_id="session-a",
        chat_id="chat-a",
        message_type="text",
        content=content,
    )


def _chunk(chunk_id, *, shop_id="shop-a", domain="logistics_policy", version="v1"):
    return KnowledgeChunk(
        chunk_id=chunk_id,
        shop_id=shop_id,
        domain=domain,
        source_type="sop",
        source_id=chunk_id,
        title=f"title-{chunk_id}",
        content=f"safe private content for {chunk_id}",
        version=version,
    )


def test_null_rag_retriever_returns_empty():
    retriever = NullRAGRetriever()

    assert retriever.retrieve(_context(), "logistics_order_status", "logistics_policy", "why") == []
    assert retriever.get_last_stats()["rag_status"] == "disabled"


def test_in_memory_rag_retriever_filters_shop_domain_and_version():
    retriever = InMemoryRAGRetriever(
        [
            _chunk("a", shop_id="shop-a", domain="logistics_policy", version="v1"),
            _chunk("b", shop_id="shop-b", domain="logistics_policy", version="v1"),
            _chunk("c", shop_id="shop-a", domain="after_sales_evidence", version="v1"),
            _chunk("d", shop_id="shop-a", domain="logistics_policy", version="v2"),
        ],
        version="v1",
    )

    hits = retriever.retrieve(_context("shop-a"), "logistics_order_status", "logistics_policy", "why", top_k=5)

    assert [hit.chunk_id for hit in hits] == ["a"]
    assert retriever.get_last_stats()["rag_hit_count"] == 1
    assert retriever.get_last_stats()["rag_domains"] == ["logistics_policy"]
    assert retriever.get_last_stats()["rag_version_pinned"] is True
    assert retriever.get_last_stats()["rag_hit_versions"] == ["v1"]
    assert retriever.get_last_stats()["rag_hit_source_types"] == ["sop"]
    assert retriever.get_last_stats()["rag_hit_content_hashes"] == [hits[0].content_hash]
    assert "safe private content" not in str(retriever.get_last_stats())


def test_in_memory_rag_retriever_rejects_empty_scope():
    retriever = InMemoryRAGRetriever([_chunk("a")])

    assert retriever.retrieve(_context(""), "product_basic", "product_catalog", "query") == []
    assert retriever.retrieve(_context("shop-a"), "product_basic", "", "query") == []
    assert retriever.retrieve(_context("shop-a"), "product_basic", "product_catalog", "") == []


class FailingEmbedding:
    model = "bge-m3"

    def embed_one(self, text):
        raise RuntimeError("embedding failed with private query")


class FailingStore:
    name = "pgvector"

    def search(self, query, vector):
        raise RuntimeError("connect failed for postgresql://user:pass@host/db")


def test_vector_store_rag_retriever_sanitizes_embedding_error():
    retriever = VectorStoreRAGRetriever(embedding_client=FailingEmbedding(), vector_store=InMemoryVectorStore())

    assert retriever.retrieve(_context(), "product_basic", "product_catalog", "private query") == []
    stats = retriever.get_last_stats()
    assert stats["rag_status"] == "error"
    assert "private query" not in stats["error_summary"]


def test_vector_store_rag_retriever_sanitizes_store_error():
    class StaticEmbedding:
        model = "bge-m3"

        def embed_one(self, text):
            return EmbeddingVector(model="bge-m3", dimension=3, vector=[0.1, 0.2, 0.3])

    retriever = VectorStoreRAGRetriever(embedding_client=StaticEmbedding(), vector_store=FailingStore())

    assert retriever.retrieve(_context(), "product_basic", "product_catalog", "query") == []
    stats = retriever.get_last_stats()
    assert stats["rag_status"] == "error"
    assert "postgresql://" not in stats["error_summary"]
    assert "pass" not in stats["error_summary"]
