import json

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from Message.workflow.answer_generator import FakeAnswerGenerator
from Message.workflow.internal_engine import InternalWorkflowEngine
from Message.workflow.intent_classifier import IntentClassification
from Message.workflow.private_trace import write_private_trace
from Message.workflow.rag_retriever import InMemoryRAGRetriever
from Message.workflow.rag_types import KnowledgeChunk
from Message.workflow.types import WorkflowContext


class _ProductClassifier:
    async def classify(self, content, content_metadata=None):
        return IntentClassification(
            intent="product_basic",
            domain="product_catalog",
            confidence=0.9,
            reason="test",
            requires_rag=True,
            requires_product_context=True,
            requires_answer_generation=True,
        )


def test_private_trace_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_WORKFLOW_DEBUG_TRACE", raising=False)
    monkeypatch.setenv("AI_WORKFLOW_DEBUG_TRACE_DIR", str(tmp_path))

    assert write_private_trace("trace-1", "event", {"buyer_message": "hello"}) is None
    assert not list(tmp_path.glob("*.json"))


def test_private_trace_writes_only_when_enabled_and_redacts_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_DEBUG_TRACE", "1")
    monkeypatch.setenv("AI_WORKFLOW_DEBUG_TRACE_DIR", str(tmp_path))

    path = write_private_trace(
        "trace/secret",
        "answer_generation",
        {
            "buyer_message": "这个多少钱",
            "api_key": "should-not-appear",
            "dsn": "postgresql://user:pass@127.0.0.1:5432/db",
            "answer_prompt": "Bearer abc token=secret ark-real-key",
        },
    )

    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    rendered = json.dumps(payload, ensure_ascii=False)
    assert payload["events"]["answer_generation"]["buyer_message"] == "这个多少钱"
    assert "should-not-appear" not in rendered
    assert "postgresql://user:pass" not in rendered
    assert "Bearer abc" not in rendered
    assert "ark-real-key" not in rendered


def test_internal_engine_private_trace_captures_runtime_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_DEBUG_TRACE", "1")
    monkeypatch.setenv("AI_WORKFLOW_DEBUG_TRACE_DIR", str(tmp_path))
    chunks = [
        KnowledgeChunk(
            chunk_id="c1",
            shop_id="shop-1",
            domain="product_catalog",
            title="测试商品",
            content="测试商品每包 80 张，价格以页面为准。",
            source_type="product",
            source_id="goods-1",
            version="v1",
        )
    ]
    engine = InternalWorkflowEngine(
        intent_classifier=_ProductClassifier(),
        answer_generator=FakeAnswerGenerator(),
        rag_retriever=InMemoryRAGRetriever(chunks=chunks, version="v1"),
    )

    result = __import__("asyncio").run(
        engine.run(
            WorkflowContext(
                trace_id="trace-private-runtime",
                shop_id="shop-1",
                content="这个一包多少张",
                metadata={"product_context": {"goods_id": "goods-1", "goods_name": "测试商品"}},
                history=[
                    {
                        "role": "buyer",
                        "content": "商品：测试商品，商品ID：goods-1",
                        "goods_id": "goods-1",
                        "goods_name": "测试商品",
                    }
                ],
            )
        )
    )

    assert result.trace["answer_generator_called"] is True
    trace_file = tmp_path / "trace-private-runtime.json"
    payload = json.loads(trace_file.read_text(encoding="utf-8"))
    events = payload["events"]
    assert events["input"]["buyer_message"] == "这个一包多少张"
    assert "conversation_text" in events["answer_generation_input"]
    assert events["rag"]["query"]
    assert events["rag"]["hits"][0]["content"]
    assert events["answer_generation_output"]["answer_text"] == result.reply_text
    assert events["final_result"]["reply_text"] == result.reply_text
