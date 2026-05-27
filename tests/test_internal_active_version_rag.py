import asyncio

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.

from Message.workflow.active_version import ActiveVersionResult
from Message.workflow.answer_generator import AnswerDraft
from Message.workflow.internal_engine import InternalWorkflowEngine
from Message.workflow.rag_retriever import InMemoryRAGRetriever
from Message.workflow.rag_types import KnowledgeChunk
from Message.workflow.types import WorkflowContext


class StaticActiveVersionResolver:
    def __init__(self, result: ActiveVersionResult):
        self.result = result

    def resolve_rag_filters(self, **kwargs):
        return self.result


class StaticAnswerGenerator:
    def generate(self, context):
        summary = ""
        if context.product_hits:
            summary = context.product_hits[0].content_summary
        elif context.sop_records:
            summary = context.sop_records[0]["approved_answer"]
        return AnswerDraft(text=f"reply from {summary}", confidence=0.9, source="test")


def _context(content: str, *, metadata=None) -> WorkflowContext:
    return WorkflowContext(
        trace_id="trace-active-version",
        shop_id="shop-1",
        user_id="user-1",
        customer_uid="buyer-1",
        buyer_id="buyer-1",
        session_id="session-1",
        chat_id="chat-1",
        dataset_id="dataset-1",
        message_type="text",
        content=content,
        metadata=dict(metadata or {}),
    )


def _chunk(chunk_id: str, *, source_type: str, source_id: str, domain: str, version_id: int, content: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=chunk_id,
        shop_id="shop-1",
        domain=domain,
        source_type=source_type,
        source_id=source_id,
        title=f"title-{chunk_id}",
        content=content,
        version=f"version-{version_id}",
        metadata={"version_id": version_id, "namespace": "knowledge_center"},
    )


def test_product_basic_uses_active_product_version_filter():
    active = ActiveVersionResult(
        resolved=True,
        version_id=22,
        version="version-22",
        source_type="product",
        source_id="goods-1",
        domain="product_catalog",
        filters={"source_type": "product", "source_id": "goods-1", "version_id": "22"},
    )
    rag = InMemoryRAGRetriever(
        [
            _chunk(
                "old",
                source_type="product",
                source_id="goods-1",
                domain="product_catalog",
                version_id=11,
                content="old usage should not be used",
            ),
            _chunk(
                "new",
                source_type="product",
                source_id="goods-1",
                domain="product_catalog",
                version_id=22,
                content="active usage should be used",
            ),
        ]
    )
    engine = InternalWorkflowEngine(
        rag_retriever=rag,
        answer_generator=StaticAnswerGenerator(),
        active_version_resolver=StaticActiveVersionResolver(active),
    )
    result = asyncio.run(
        engine.run(
            _context(
                "这个怎么用",
                metadata={
                    "product_context": {
                        "status": "resolved",
                        "source": "message_metadata",
                        "goods_id": "goods-1",
                        "goods_name": "Test Product",
                    }
                },
            )
        )
    )

    assert result.trace["active_version_resolved"] is True
    assert result.trace["active_version_id"] == 22
    assert result.trace["active_source_type"] == "product"
    assert result.trace["active_source_id"] == "goods-1"
    assert result.trace["rag_hit_count"] == 1
    assert result.trace["rag_hit_version_ids"] == ["22"]
    assert "active usage" in result.reply_text
    assert "old usage" not in result.reply_text


def test_logistics_uses_active_sop_domain_version_filter():
    active = ActiveVersionResult(
        resolved=True,
        version_id=33,
        version="version-33",
        source_type="sop",
        source_id="sop-33",
        domain="logistics_policy",
        filters={"source_type": "sop", "version_id": "33"},
    )
    rag = InMemoryRAGRetriever(
        [
            _chunk(
                "old-sop",
                source_type="sop",
                source_id="sop-11",
                domain="logistics_policy",
                version_id=11,
                content="old logistics policy",
            ),
            _chunk(
                "new-sop",
                source_type="sop",
                source_id="sop-33",
                domain="logistics_policy",
                version_id=33,
                content="active logistics policy",
            ),
        ]
    )
    engine = InternalWorkflowEngine(
        rag_retriever=rag,
        answer_generator=StaticAnswerGenerator(),
        active_version_resolver=StaticActiveVersionResolver(active),
    )
    result = asyncio.run(engine.run(_context("物流多久更新")))

    assert result.trace["active_version_resolved"] is True
    assert result.trace["active_version_id"] == 33
    assert result.trace["active_source_type"] == "sop"
    assert result.trace["active_domain"] == "logistics_policy"
    assert result.trace["rag_hit_count"] == 1
    assert result.trace["rag_hit_version_ids"] == ["33"]
    assert "active logistics" in result.reply_text
    assert "old logistics" not in result.reply_text
