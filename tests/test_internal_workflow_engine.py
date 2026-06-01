import asyncio

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from Message.workflow.conversation_context import (
    ConversationRecord,
    InMemoryConversationContextRepository,
    stable_hash,
)
from Message.workflow.answer_generator import AnswerDraft
from Message.workflow.intent_classifier import IntentClassification
from Message.workflow.internal_engine import InternalWorkflowEngine
from Message.workflow.knowledge import ProductKnowledgeRetriever
from Message.workflow.embedding_client import FakeEmbeddingClient
from Message.workflow.rag_retriever import VectorStoreRAGRetriever
from Message.workflow.rag_types import KnowledgeChunk, RetrievalHit
from Message.workflow.types import WorkflowAction, WorkflowContext
from Message.workflow.vector_store import InMemoryVectorStore


def _context(
    content: str,
    *,
    shop_id: str = "shop-1",
    goods_context=None,
    message_type: str = "text",
    metadata=None,
) -> WorkflowContext:
    return WorkflowContext(
        trace_id="trace-internal-1",
        shop_id=shop_id,
        user_id="user-1",
        customer_uid="buyer-1",
        buyer_id="buyer-1",
        session_id="session-1",
        chat_id="chat-1",
        dataset_id="dataset-1",
        message_type=message_type,
        content=content,
        goods_context=goods_context,
        metadata=dict(metadata or {}),
    )


async def _run(
    content: str,
    *,
    engine=None,
    shop_id: str = "shop-1",
    goods_context=None,
    message_type: str = "text",
    metadata=None,
):
    selected = engine or InternalWorkflowEngine()
    return await selected.run(
        _context(
            content,
            shop_id=shop_id,
            goods_context=goods_context,
            message_type=message_type,
            metadata=metadata,
        )
    )


def _keyword(group: str, index: int = 0) -> str:
    return getattr(InternalWorkflowEngine, group)[index]


def _product_engine() -> InternalWorkflowEngine:
    retriever = ProductKnowledgeRetriever(
        [
            {
                "shop_id": "shop-1",
                "domain": "product_catalog",
                "goods_id": "mini-balm",
                "goods_name": "Mini Balm",
                "price": "99",
                "specifications": "100ml",
                "usage_method": "Use after cleansing.",
                "ingredients": "Shea butter, glycerin",
                "shelf_life": "24 months",
                "warnings": "Patch test first.",
                "manual_notes": "Page display is authoritative.",
            },
            {
                "shop_id": "shop-2",
                "domain": "product_catalog",
                "goods_id": "other-shop-product",
                "goods_name": "Other Shop Product",
                "price": "129",
                "usage_method": "Do not return across shops.",
            },
        ]
    )
    return InternalWorkflowEngine(knowledge_retriever=retriever)


class SpyIntentClassifier:
    def __init__(self, classification: IntentClassification):
        self.classification = classification
        self.calls = []

    async def classify(self, content, content_metadata=None):
        self.calls.append((content, content_metadata))
        return self.classification


class SpyKnowledgeRetriever:
    def __init__(self, hits=None):
        self.hits = hits or []
        self.calls = []

    def search(self, *, shop_id, domain, query, limit=3):
        self.calls.append({"shop_id": shop_id, "domain": domain, "query": query, "limit": limit})
        return list(self.hits)


class SpyRAGRetriever:
    def __init__(self, hits=None):
        self.hits = hits or []
        self.calls = []
        self._last_stats = {"rag_status": "not_called", "rag_hit_count": 0}

    def retrieve(self, context, intent, domain, query, top_k=3):
        self.calls.append({"shop_id": context.shop_id, "intent": intent, "domain": domain, "query": query, "top_k": top_k})
        selected = [hit for hit in self.hits if hit.shop_id == context.shop_id and hit.domain == domain]
        self._last_stats = {
            "rag_status": "hit" if selected else "empty",
            "rag_hit_count": len(selected),
            "rag_domains": sorted({hit.domain for hit in selected}),
            "rag_top_score": selected[0].score if selected else 0.0,
            "vector_store": "in_memory",
            "embedding_model": "fake",
            "retrieval_source": "fake_rag",
        }
        return selected

    def get_last_stats(self):
        return dict(self._last_stats)


def _rag_hit(domain="product_catalog", *, shop_id="shop-1", score=0.91, source_type="rag_fixture"):
    return RetrievalHit(
        chunk_id=f"{shop_id}-{domain}",
        shop_id=shop_id,
        domain=domain,
        title=f"{domain} title",
        content_summary="safe summarized RAG hit",
        score=score,
        source_type=source_type,
        source_id="fixture-1",
        version="rag-v1",
        content_hash="hash-rag",
        metadata={"domain": domain},
    )


class FakeProductKnowledgeRepository:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def load_records(self, *, shop_id):
        self.calls.append(shop_id)
        return [record for record in self.records if record["shop_id"] == shop_id]


class FakeStatsProductKnowledgeRepository:
    def __init__(self, records, ttl_seconds=300):
        self.records = records
        self.ttl_seconds = ttl_seconds
        self.calls = []
        self._cache = {}
        self._last_stats = None

    def load_records(self, *, shop_id):
        if shop_id in self._cache:
            self._last_stats = {"cache_hit": True, "ttl_seconds": self.ttl_seconds}
            return [dict(record) for record in self._cache[shop_id]]
        self.calls.append(shop_id)
        records = [dict(record) for record in self.records if record["shop_id"] == shop_id]
        self._cache[shop_id] = records
        self._last_stats = {"cache_hit": False, "ttl_seconds": self.ttl_seconds}
        return [dict(record) for record in records]

    def get_last_stats(self):
        return self._last_stats


class FakeSOPProvider:
    def __init__(self, records):
        self.records = records


class SpyAnswerGenerator:
    def __init__(self, text="Generated safe answer.", confidence=0.88):
        self.text = text
        self.confidence = confidence
        self.calls = []

    def generate(self, context):
        self.calls.append(context)
        return AnswerDraft(
            text=self.text,
            confidence=self.confidence,
            source="fake",
            used_knowledge_refs=[{"source": "fake"}],
            used_sop_domains=list({getattr(record, "domain", None) or record.get("domain", "") for record in context.sop_records})
            if context.sop_records
            else [],
            used_history_count=len(context.history_window),
        )


class EmptyAnswerGenerator(SpyAnswerGenerator):
    def __init__(self, raw_error_type="URLError", raw_error_summary="provider request failed"):
        super().__init__(text="")
        self.raw_error_type = raw_error_type
        self.raw_error_summary = raw_error_summary

    def generate(self, context):
        self.calls.append(context)
        return AnswerDraft(
            text="",
            confidence=0.0,
            source="openai_compatible",
            raw_error_type=self.raw_error_type,
            raw_error_summary=self.raw_error_summary,
            used_history_count=len(context.history_window),
        )


class ContextAwareAnswerGenerator(SpyAnswerGenerator):
    def generate(self, context):
        self.calls.append(context)
        return AnswerDraft(
            text=(
                "亲，这款商品信息请以商品页面和结算页为准；"
                "如需进一步确认，我可以帮您转人工核实。"
            ),
            confidence=self.confidence,
            source="fake",
            used_history_count=len(context.history_window),
        )


def _conversation_repo(*, pending_human=False, content="private previous buyer message"):
    return InMemoryConversationContextRepository(
        [
            ConversationRecord(
                shop_id="shop-1",
                user_id="user-1",
                buyer_id="buyer-1",
                session_id="session-1",
                role="buyer",
                message_type="text",
                content=content,
                created_at="2026-05-21T01:00:00Z",
                source="synthetic_test",
                human_state="pending_human" if pending_human else "",
                pending_human=pending_human,
                intent="after_sales_evidence_collection" if pending_human else "product_basic",
                action="transfer_human" if pending_human else "reply",
            )
        ]
    )


class CapturingConversationRepository:
    def __init__(self, records):
        self.delegate = InMemoryConversationContextRepository(records)
        self.calls = []

    def load_context(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.delegate.load_context(**kwargs)


def test_explicit_human_request_transfers_to_human():
    async def scenario():
        result = await _run(_keyword("_EXPLICIT_HUMAN_KEYWORDS"))

        assert result.action == WorkflowAction.TRANSFER_HUMAN
        assert result.intent == "explicit_human_request"
        assert result.reason == "buyer_requested_human"
        assert result.trace["workflow_version"] == "internal-v1"
        assert result.trace["sop_version"] is None
        assert result.trace["knowledge_version"] is None
        assert result.trace["sop_domains"] == []
        assert result.trace["sop_record_count"] == 0

    asyncio.run(scenario())


def test_pending_human_conversation_transfers_before_product_repository():
    async def scenario():
        repository = FakeStatsProductKnowledgeRepository(
            [{"shop_id": "shop-1", "domain": "product_catalog", "goods_name": "Mini Balm", "price": "99"}]
        )
        engine = InternalWorkflowEngine(
            knowledge_repository=repository,
            conversation_context_repository=_conversation_repo(pending_human=True),
        )

        result = await _run("Mini Balm price", engine=engine, goods_context={"goods_name": "Mini Balm"})

        assert result.action == WorkflowAction.TRANSFER_HUMAN
        assert result.intent == "pending_human_lock"
        assert result.reason == "pending_human_conversation"
        assert "pending_human" in result.risk_flags
        assert repository.calls == []
        assert result.trace["pending_human"] is True
        assert result.trace["history_message_count"] == 1
        assert result.trace["history_window_size"] == 1
        assert result.trace["buyer_id_hash"] == stable_hash("buyer-1")
        assert result.trace["session_id_hash"] == stable_hash("session-1")

    asyncio.run(scenario())


def test_conversation_history_is_attached_as_summary_only():
    async def scenario():
        full_history = "private previous buyer message"
        engine = InternalWorkflowEngine(conversation_context_repository=_conversation_repo(content=full_history))

        context = _context("hello")
        result = await engine.run(context)

        assert result.trace["pending_human"] is False
        assert result.trace["history_message_count"] == 1
        assert result.trace["history_window_size"] == 1
        assert len(context.history) == 1
        history_item = context.history[0]
        assert set(history_item) == {
            "role",
            "message_type",
            "content",
            "content_summary",
            "content_hash",
            "created_at",
            "source",
        }
        assert history_item["content_hash"] == stable_hash(full_history)
        assert history_item["content"] == full_history
        assert full_history not in repr(result.trace)

    asyncio.run(scenario())


def test_internal_engine_requests_full_context_window_for_prompt_compression():
    async def scenario():
        records = [
            ConversationRecord(
                shop_id="shop-1",
                user_id="user-1",
                buyer_id="buyer-1",
                session_id="session-1",
                role="buyer",
                message_type="text",
                content=f"history {index}",
                created_at=f"2026-05-21T01:{index:02d}:00Z",
                source="synthetic_test",
            )
            for index in range(25)
        ]
        repository = CapturingConversationRepository(records)
        engine = InternalWorkflowEngine(conversation_context_repository=repository)

        context = _context("hello")
        result = await engine.run(context)

        assert repository.calls[0]["limit"] == 40
        assert result.trace["history_message_count"] == 25
        assert result.trace["history_window_size"] == 25
        assert len(context.history) == 25
        assert "history 0" not in repr(result.trace)

    asyncio.run(scenario())


def test_fake_history_context_is_visible_without_changing_existing_flow():
    async def scenario():
        engine = InternalWorkflowEngine(conversation_context_repository=_conversation_repo(content="previous spec question"))

        result = await _run(_keyword("_PRODUCT_BASIC_KEYWORDS"), engine=engine)

        assert result.intent == "ask_product_clarification"
        assert result.trace["history_message_count"] == 1
        assert result.trace["history_window_size"] == 1
        assert result.trace["pending_human"] is False
        assert "previous spec question" not in repr(result.trace)

    asyncio.run(scenario())


def test_redline_messages_transfer_to_human():
    async def scenario():
        for content in (_keyword("_REDLINE_KEYWORDS", 0), _keyword("_REDLINE_KEYWORDS", 3), _keyword("_REDLINE_KEYWORDS", 5)):
            result = await _run(content)

            assert result.action == WorkflowAction.TRANSFER_HUMAN
            assert result.intent == "human_escalation_redline"
            assert "redline" in result.risk_flags
            assert not result.reply_text

    asyncio.run(scenario())


def test_after_sales_messages_request_evidence_without_promises():
    async def scenario():
        forbidden = ("refund", "compensate", "resend", "replace")
        for content in (_keyword("_EVIDENCE_KEYWORDS", 0), _keyword("_EVIDENCE_KEYWORDS", 3), _keyword("_EVIDENCE_KEYWORDS", 5)):
            result = await _run(content)

            assert result.action == WorkflowAction.REQUEST_EVIDENCE
            assert result.intent == "after_sales_evidence_collection"
            assert result.reason == "request_buyer_evidence"
            assert result.reply_text
            assert all(term not in result.reply_text.lower() for term in forbidden)

    asyncio.run(scenario())


def test_logistics_status_reply_has_order_page_boundary():
    async def scenario():
        result = await _run(_keyword("_LOGISTICS_KEYWORDS"))

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "logistics_order_status"
        assert "already shipped" not in result.reply_text.lower()
        assert "tomorrow" not in result.reply_text.lower()

    asyncio.run(scenario())


def test_promotion_policy_reply_avoids_private_discount_promise():
    async def scenario():
        result = await _run(_keyword("_PROMOTION_KEYWORDS"))

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "promotion_policy"
        assert "private discount" not in result.reply_text.lower()

    asyncio.run(scenario())


def test_sensitive_user_safety_reply_is_conservative():
    async def scenario():
        result = await _run(_keyword("_SENSITIVE_USER_KEYWORDS"))

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "sensitive_user_safety"
        assert "guarantee" not in result.reply_text.lower()
        assert "definitely safe" not in result.reply_text.lower()

    asyncio.run(scenario())


def test_sensitive_user_safety_common_messages_do_not_skip():
    async def scenario():
        for content in ("孕妇能用吗", "小孩能用吗", "敏感肌能用吗", "过敏能用吗"):
            result = await _run(content)

            assert result.action == WorkflowAction.REPLY
            assert result.intent == "sensitive_user_safety"
            assert result.reply_text
            assert "一定能用" not in result.reply_text
            assert "绝对安全" not in result.reply_text

    asyncio.run(scenario())


def test_product_basic_falls_back_when_knowledge_is_not_found():
    async def scenario():
        result = await _run(_keyword("_PRODUCT_BASIC_KEYWORDS"))

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "ask_product_clarification"
        assert result.reason == "product_context_missing_required"
        assert "哪款商品" in result.reply_text

    asyncio.run(scenario())


def test_product_pronoun_without_product_context_asks_clarification_without_rag():
    async def scenario():
        rag = SpyRAGRetriever([_rag_hit("product_catalog")])
        generator = SpyAnswerGenerator(text="should not be used")
        engine = InternalWorkflowEngine(rag_retriever=rag, answer_generator=generator)

        result = await _run("这个多少钱", engine=engine)

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "ask_product_clarification"
        assert result.reason == "product_context_missing_required"
        assert "哪款商品" in result.reply_text
        assert rag.calls == []
        assert generator.calls == []
        assert result.trace["product_context_status"] == "missing_required"

    asyncio.run(scenario())


def test_product_context_rag_hit_calls_answer_generator_and_avoids_engine_text():
    async def scenario():
        rag = SpyRAGRetriever([_rag_hit("product_catalog", score=0.95)])
        generator = ContextAwareAnswerGenerator()
        engine = InternalWorkflowEngine(rag_retriever=rag, answer_generator=generator)

        result = await _run("这个多少钱", engine=engine, goods_context={"goods_id": "mini-balm", "goods_name": "Mini Balm"})

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "product_basic"
        assert result.reason == "rag_answer_generated"
        assert len(generator.calls) == 1
        assert generator.calls[0].intent == "product_basic"
        assert generator.calls[0].product_context["goods_id"] == "mini-balm"
        assert result.trace["product_context_status"] == "resolved"
        assert result.trace["product_context_source"] == "message_card"
        assert result.trace["rag_hit_count"] == 1
        assert "Product:" not in result.reply_text
        assert "Goods ID:" not in result.reply_text
        assert "Specifications:" not in result.reply_text

    asyncio.run(scenario())


def test_product_context_can_be_restored_from_history_product_card():
    async def scenario():
        rag = SpyRAGRetriever([_rag_hit("product_catalog", score=0.95)])
        generator = ContextAwareAnswerGenerator()
        engine = InternalWorkflowEngine(rag_retriever=rag, answer_generator=generator)
        context = _context(_keyword("_PRODUCT_BASIC_KEYWORDS"), goods_context=None)
        context.history = [
            {
                "role": "user",
                "content": "previous product card",
                "goods_id": "mini-balm",
                "goods_name": "Mini Balm",
                "message_type": "64",
            }
        ]

        result = await engine.run(context)

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "product_basic"
        assert len(generator.calls) == 1
        assert generator.calls[0].product_context["goods_id"] == "mini-balm"
        assert result.trace["product_context_status"] == "resolved"
        assert result.trace["product_context_source"] == "history"
        assert result.trace["product_context_inherited"] is True
        assert result.trace["product_context_age_messages"] == 1
        assert rag.calls[0]["domain"] == "product_catalog"

    asyncio.run(scenario())


def test_domain_keywords_use_rag_and_answer_generator_when_available():
    async def scenario():
        cases = [
            ("为什么还没到", "logistics_policy", "logistics_order_status"),
            ("收到破损了怎么办", "after_sales_evidence", "after_sales_evidence_collection"),
            ("能不能便宜点", "promotion_policy", "promotion_policy"),
            ("孕妇能用吗", "sensitive_user_safety", "sensitive_user_safety"),
        ]
        for message, domain, intent in cases:
            rag = SpyRAGRetriever([_rag_hit(domain, source_type="sop")])
            generator = SpyAnswerGenerator(text=f"Generated safe {domain} answer.")
            engine = InternalWorkflowEngine(rag_retriever=rag, answer_generator=generator)

            result = await _run(message, engine=engine)

            assert result.action in {WorkflowAction.REPLY, WorkflowAction.REQUEST_EVIDENCE}
            assert result.intent == intent
            assert len(generator.calls) == 1
            assert generator.calls[0].sop_records
            assert rag.calls[0]["domain"] == domain
            assert rag.calls[0]["top_k"] == 3
            assert result.trace["selected_domain"] == domain
            assert result.trace["used_rag_hit_count"] == 1

    asyncio.run(scenario())


def test_classifier_sensitive_user_safety_uses_domain_rag_and_answer_generator_without_skip():
    async def scenario():
        classifier = SpyIntentClassifier(
            IntentClassification(
                intent="sensitive_user_safety",
                domain="sensitive_user_safety",
                confidence=0.92,
                reason="classifier_sensitive_safety_question",
                requires_rag=True,
                requires_answer_generation=True,
            )
        )
        rag = SpyRAGRetriever([_rag_hit("sensitive_user_safety", source_type="sop")])
        generator = SpyAnswerGenerator(text="亲，建议先看商品说明和成分，孕妇儿童或过敏情况可咨询专业人士。")
        engine = InternalWorkflowEngine(
            intent_classifier=classifier,
            rag_retriever=rag,
            answer_generator=generator,
        )

        result = await _run("特殊人群咨询", engine=engine)

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "sensitive_user_safety"
        assert result.reason == "rag_policy_answer_generated"
        assert len(generator.calls) == 1
        assert generator.calls[0].intent == "sensitive_user_safety"
        assert rag.calls[0]["domain"] == "sensitive_user_safety"
        assert result.trace["classifier_intent_raw"] == "sensitive_user_safety"
        assert result.trace["normalized_intent"] == "sensitive_user_safety"
        assert result.trace["selected_domain"] == "sensitive_user_safety"
        assert "internal_classifier_intent_not_implemented" not in result.reason
        assert "一定能用" not in result.reply_text
        assert "绝对安全" not in result.reply_text

    asyncio.run(scenario())


def test_classifier_sensitive_user_safety_guardrail_block_transfers_to_human():
    async def scenario():
        classifier = SpyIntentClassifier(
            IntentClassification(
                intent="sensitive_user_safety",
                domain="sensitive_user_safety",
                confidence=0.92,
                reason="classifier_sensitive_safety_question",
                requires_rag=True,
                requires_answer_generation=True,
            )
        )
        rag = SpyRAGRetriever([_rag_hit("sensitive_user_safety", source_type="sop")])
        generator = SpyAnswerGenerator(text="孕妇一定能用，绝对安全。")
        engine = InternalWorkflowEngine(
            intent_classifier=classifier,
            rag_retriever=rag,
            answer_generator=generator,
        )

        result = await _run("特殊人群咨询", engine=engine)

        assert result.action == WorkflowAction.TRANSFER_HUMAN
        assert result.reason == "output_guardrail_policy_violation"
        assert result.trace["guardrail_status"] == "blocked"
        assert result.trace["classifier_intent_raw"] == "sensitive_user_safety"
        assert result.trace["normalized_intent"] == "sensitive_user_safety"

    asyncio.run(scenario())


def test_product_price_reply_uses_page_or_checkout_boundary():
    async def scenario():
        generator = SpyAnswerGenerator(text="亲，这款价格请以商品页面和结算页显示为准。")
        engine = _product_engine()
        engine.answer_generator = generator
        result = await _run(
            _keyword("_PRODUCT_BASIC_KEYWORDS"),
            engine=engine,
            goods_context={"goods_name": "Mini Balm"},
        )

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "product_basic"
        assert result.reason == "product_answer_generated"
        assert "结算页" in result.reply_text
        assert len(generator.calls) == 1
        assert result.knowledge_refs
        assert result.knowledge_refs[0]["title"] == "Mini Balm"
        assert result.trace["knowledge_source"] == "retriever"
        assert result.trace["knowledge_hit_count"] >= 1
        assert result.trace["knowledge_version"] == "product_repository"
        assert result.trace["product_cache_hit"] is None

    asyncio.run(scenario())


def test_fake_answer_generator_can_render_product_basic_with_history_trace():
    async def scenario():
        generator = SpyAnswerGenerator(text="Generated safe product answer.")
        engine = InternalWorkflowEngine(
            knowledge_retriever=_product_engine().knowledge_retriever,
            answer_generator=generator,
            conversation_context_repository=_conversation_repo(content="private previous buyer message"),
        )

        result = await _run(
            _keyword("_PRODUCT_BASIC_KEYWORDS"),
            engine=engine,
            goods_context={"goods_name": "Mini Balm"},
        )

        assert result.action == WorkflowAction.REPLY
        assert result.reply_text == "Generated safe product answer."
        assert len(generator.calls) == 1
        assert generator.calls[0].intent == "product_basic"
        assert generator.calls[0].history_window
        assert result.trace["answer_generator"] == "fake"
        assert result.trace["answer_generation_source"] == "fake"
        assert result.trace["used_history_count"] == 1
        assert result.trace["prompt_hash"]
        assert "private previous buyer message" not in repr(result.trace)

    asyncio.run(scenario())


def test_answer_generator_can_render_sop_domain_response():
    async def scenario():
        generator = SpyAnswerGenerator(text="Generated safe logistics answer.")
        provider = FakeSOPProvider(
            [{"shop_id": "shop-1", "domain": "logistics_policy", "version": "sop-v1", "id": "sop-logistics"}]
        )
        engine = InternalWorkflowEngine(sop_provider=provider, answer_generator=generator)

        result = await _run(_keyword("_LOGISTICS_KEYWORDS"), engine=engine)

        assert result.action == WorkflowAction.REPLY
        assert result.reply_text == "Generated safe logistics answer."
        assert result.trace["answer_generator"] == "fake"
        assert result.trace["sop_version"] == "sop-v1"
        assert result.trace["prompt_hash"]

    asyncio.run(scenario())


def test_redline_and_pending_human_do_not_call_answer_generator():
    async def scenario():
        generator = SpyAnswerGenerator(text="should not run")
        redline = await _run(_keyword("_REDLINE_KEYWORDS", 3), engine=InternalWorkflowEngine(answer_generator=generator))
        pending = await _run(
            _keyword("_PRODUCT_BASIC_KEYWORDS"),
            engine=InternalWorkflowEngine(
                answer_generator=generator,
                conversation_context_repository=_conversation_repo(pending_human=True),
            ),
        )

        assert redline.action == WorkflowAction.TRANSFER_HUMAN
        assert pending.action == WorkflowAction.TRANSFER_HUMAN
        assert generator.calls == []

    asyncio.run(scenario())


def test_dangerous_answer_generator_draft_is_guardrailed():
    async def scenario():
        generator = SpyAnswerGenerator(text="We will compensate you today.")
        engine = InternalWorkflowEngine(
            knowledge_retriever=_product_engine().knowledge_retriever,
            answer_generator=generator,
        )

        result = await _run(
            _keyword("_PRODUCT_BASIC_KEYWORDS"),
            engine=engine,
            goods_context={"goods_name": "Mini Balm"},
        )

        assert result.action == WorkflowAction.TRANSFER_HUMAN
        assert result.reason == "output_guardrail_policy_violation"
        assert "policy_violation" in result.risk_flags
        assert result.trace["answer_generator"] == "fake"

    asyncio.run(scenario())


def test_product_usage_ingredients_and_shelf_life_replies_from_knowledge():
    async def scenario():
        engine = _product_engine()
        engine.answer_generator = SpyAnswerGenerator(text="亲，已根据商品知识为您说明，具体以商品页面为准。")

        usage = await _run(_keyword("_PRODUCT_BASIC_KEYWORDS", 3), engine=engine, goods_context={"goods_name": "Mini Balm"})
        ingredients = await _run(f"Mini Balm {_keyword('_PRODUCT_BASIC_KEYWORDS', 4)}", engine=engine)
        shelf_life = await _run(f"Mini Balm {_keyword('_PRODUCT_BASIC_KEYWORDS', 5)}", engine=engine)

        assert usage.action == WorkflowAction.REPLY
        assert usage.intent == "product_basic"
        assert usage.trace["answer_generator_called"] is True
        assert ingredients.action == WorkflowAction.REPLY
        assert ingredients.trace["answer_generator_called"] is True
        assert shelf_life.action == WorkflowAction.REPLY
        assert shelf_life.trace["answer_generator_called"] is True

    asyncio.run(scenario())


def test_product_retrieval_does_not_cross_shop_boundary():
    async def scenario():
        result = await _run(
            f"Other Shop Product {_keyword('_PRODUCT_BASIC_KEYWORDS', 3)}",
            engine=_product_engine(),
            shop_id="shop-1",
        )

        assert result.action == WorkflowAction.REPLY
        assert result.reason == "product_context_missing_required"
        assert not result.knowledge_refs

    asyncio.run(scenario())


def test_sensitive_rule_wins_before_product_knowledge():
    async def scenario():
        result = await _run(f"{_keyword('_SENSITIVE_USER_KEYWORDS')} Mini Balm", engine=_product_engine())

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "sensitive_user_safety"
        assert not result.knowledge_refs

    asyncio.run(scenario())


def test_hard_rules_still_win_with_product_retriever():
    async def scenario():
        engine = _product_engine()

        evidence = await _run(_keyword("_EVIDENCE_KEYWORDS"), engine=engine)
        redline = await _run(_keyword("_REDLINE_KEYWORDS", 3), engine=engine)
        logistics = await _run(_keyword("_LOGISTICS_KEYWORDS"), engine=engine)
        promotion = await _run(_keyword("_PROMOTION_KEYWORDS"), engine=engine)

        assert evidence.action == WorkflowAction.REQUEST_EVIDENCE
        assert redline.action == WorkflowAction.TRANSFER_HUMAN
        assert redline.intent == "human_escalation_redline"
        assert logistics.intent == "logistics_order_status"
        assert promotion.intent == "promotion_policy"

    asyncio.run(scenario())


def test_hard_rule_precheck_does_not_call_classifier_or_retriever():
    async def scenario():
        classifier = SpyIntentClassifier(
            IntentClassification(intent="product_basic", confidence=0.99, reason="should_not_run")
        )
        retriever = SpyKnowledgeRetriever()
        engine = InternalWorkflowEngine(knowledge_retriever=retriever, intent_classifier=classifier)

        result = await _run(_keyword("_REDLINE_KEYWORDS", 3), engine=engine)

        assert result.action == WorkflowAction.TRANSFER_HUMAN
        assert result.intent == "human_escalation_redline"
        assert classifier.calls == []
        assert retriever.calls == []

    asyncio.run(scenario())


def test_hard_rule_precheck_does_not_call_repository_or_emit_cache_trace():
    async def scenario():
        repository = FakeStatsProductKnowledgeRepository(
            [{"shop_id": "shop-1", "domain": "product_catalog", "goods_name": "Mini Balm", "usage_method": "Use"}]
        )
        engine = InternalWorkflowEngine(knowledge_repository=repository)

        result = await _run(_keyword("_REDLINE_KEYWORDS", 3), engine=engine)

        assert result.action == WorkflowAction.TRANSFER_HUMAN
        assert repository.calls == []
        assert "product_cache_hit" not in result.trace
        assert "product_cache_ttl_seconds" not in result.trace

    asyncio.run(scenario())


def test_product_basic_trace_includes_repository_cache_miss_and_hit_stats():
    async def scenario():
        repository = FakeStatsProductKnowledgeRepository(
            [{"shop_id": "shop-1", "domain": "product_catalog", "goods_name": "Mini Balm", "price": "99"}],
            ttl_seconds=120,
        )
        engine = InternalWorkflowEngine(knowledge_repository=repository)

        first = await _run(_keyword("_PRODUCT_BASIC_KEYWORDS"), engine=engine, goods_context={"goods_name": "Mini Balm"})
        second = await _run(_keyword("_PRODUCT_BASIC_KEYWORDS"), engine=engine, goods_context={"goods_name": "Mini Balm"})

        assert first.trace["knowledge_source"] == "repository"
        assert first.trace["knowledge_hit_count"] == 1
        assert first.trace["knowledge_version"] == "product_repository"
        assert first.trace["product_cache_hit"] is False
        assert first.trace["product_cache_ttl_seconds"] == 120
        assert second.trace["product_cache_hit"] is True
        assert second.trace["product_cache_ttl_seconds"] == 120
        assert repository.calls == ["shop-1"]

    asyncio.run(scenario())


def test_product_basic_trace_does_not_include_full_product_details():
    async def scenario():
        full_detail = "FULL_PRODUCT_DETAIL_DO_NOT_TRACE"
        repository = FakeStatsProductKnowledgeRepository(
            [
                {
                    "shop_id": "shop-1",
                    "domain": "product_catalog",
                    "goods_name": "Sensitive Full Product Name",
                    "price": "99",
                    "raw_detail_json": full_detail,
                    "manual_notes": "Sensitive Manual Detail",
                }
            ]
        )
        engine = InternalWorkflowEngine(knowledge_repository=repository)

        result = await _run(
            _keyword("_PRODUCT_BASIC_KEYWORDS"),
            engine=engine,
            goods_context={"goods_name": "Sensitive Full Product Name"},
        )
        trace_repr = repr(result.trace)

        assert result.trace["knowledge_hit_count"] == 1
        assert "Sensitive Full Product Name" not in trace_repr
        assert full_detail not in trace_repr
        assert "Sensitive Manual Detail" not in trace_repr

    asyncio.run(scenario())


def test_classifier_product_basic_routes_to_repository_backed_knowledge():
    async def scenario():
        classifier = SpyIntentClassifier(
            IntentClassification(intent="product_basic", confidence=0.91, reason="classifier_product")
        )
        repository = FakeProductKnowledgeRepository(
            [
                {"shop_id": "shop-1", "domain": "product_catalog", "goods_name": "Mini Balm", "usage_method": "Use"},
                {"shop_id": "shop-2", "domain": "product_catalog", "goods_name": "Other", "usage_method": "Wrong"},
            ]
        )
        engine = InternalWorkflowEngine(
            knowledge_repository=repository,
            intent_classifier=classifier,
            answer_generator=SpyAnswerGenerator(text="亲，这款商品请以商品页面为准。"),
        )

        result = await _run("tell me", engine=engine, shop_id="shop-1", goods_context={"goods_name": "Mini Balm"})

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "product_basic"
        assert result.reason == "product_answer_generated"
        assert result.trace["answer_generator_called"] is True
        assert "Wrong" not in result.reply_text
        assert repository.calls == ["shop-1"]

    asyncio.run(scenario())


def test_classifier_extended_domain_routes_product_to_rag():
    async def scenario():
        classifier = SpyIntentClassifier(
            IntentClassification(
                intent="product_basic",
                domain="product_catalog",
                confidence=0.91,
                reason="classifier_product",
                requires_rag=True,
                requires_product_context=True,
            )
        )
        rag = SpyRAGRetriever([_rag_hit("product_catalog")])
        generator = SpyAnswerGenerator(text="亲，这款信息以商品页和结算页为准。")
        engine = InternalWorkflowEngine(
            rag_retriever=rag,
            intent_classifier=classifier,
            answer_generator=generator,
        )

        result = await _run("tell me", engine=engine, goods_context={"goods_id": "mini-balm", "goods_name": "Mini Balm"})

        assert result.action == WorkflowAction.REPLY
        assert result.reason == "rag_answer_generated"
        assert rag.calls[0]["domain"] == "product_catalog"
        assert generator.calls

    asyncio.run(scenario())


def test_classifier_clarification_needed_does_not_call_product_rag():
    async def scenario():
        classifier = SpyIntentClassifier(
            IntentClassification(
                intent="ask_product_clarification",
                domain=None,
                confidence=0.86,
                reason="missing product anchor",
                clarification_needed=True,
                requires_rag=False,
            )
        )
        rag = SpyRAGRetriever([_rag_hit("product_catalog")])
        engine = InternalWorkflowEngine(rag_retriever=rag, intent_classifier=classifier)

        result = await _run("tell me about this", engine=engine)

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "ask_product_clarification"
        assert result.trace["product_context_status"] == "missing_required"
        assert rag.calls == []

    asyncio.run(scenario())


def test_classifier_should_transfer_human_takes_precedence():
    async def scenario():
        classifier = SpyIntentClassifier(
            IntentClassification(
                intent="product_basic",
                domain="product_catalog",
                confidence=0.91,
                reason="classified but unsafe",
                should_transfer_human=True,
                risk_flags=["redline"],
            )
        )
        rag = SpyRAGRetriever([_rag_hit("product_catalog")])
        engine = InternalWorkflowEngine(rag_retriever=rag, intent_classifier=classifier)

        result = await _run("tell me", engine=engine, goods_context={"goods_name": "Mini Balm"})

        assert result.action == WorkflowAction.TRANSFER_HUMAN
        assert result.intent == "human_escalation_redline"
        assert rag.calls == []

    asyncio.run(scenario())


def test_classifier_should_request_evidence_uses_after_sales_path():
    async def scenario():
        classifier = SpyIntentClassifier(
            IntentClassification(
                intent="after_sales_evidence_collection",
                domain="after_sales_evidence",
                confidence=0.91,
                reason="damaged item",
                requires_rag=True,
                should_request_evidence=True,
            )
        )
        rag = SpyRAGRetriever([_rag_hit("after_sales_evidence", source_type="sop")])
        generator = SpyAnswerGenerator(text="亲，请提供问题照片、外包装照片和订单信息，客服会为您核实。")
        engine = InternalWorkflowEngine(
            rag_retriever=rag,
            intent_classifier=classifier,
            answer_generator=generator,
        )

        result = await _run("package issue", engine=engine)

        assert result.action == WorkflowAction.REQUEST_EVIDENCE
        assert result.intent == "after_sales_evidence_collection"
        assert rag.calls[0]["domain"] == "after_sales_evidence"
        assert generator.calls

    asyncio.run(scenario())


def test_classifier_policy_intents_without_sop_source_do_not_use_unsupported_fallback():
    async def scenario():
        cases = [
            (
                IntentClassification(
                    intent="after_sales_evidence_collection",
                    domain="after_sales_evidence",
                    confidence=0.91,
                    reason="damaged item",
                    requires_rag=True,
                    should_request_evidence=True,
                ),
                "classifier-only after sales",
                "after_sales_evidence_collection",
                WorkflowAction.REQUEST_EVIDENCE,
            ),
            (
                IntentClassification(
                    intent="logistics_order_status",
                    domain="logistics_policy",
                    confidence=0.91,
                    reason="shipping question",
                    requires_rag=True,
                ),
                "classifier-only shipping",
                "logistics_order_status",
                WorkflowAction.REPLY,
            ),
            (
                IntentClassification(
                    intent="promotion_policy",
                    domain="promotion_policy",
                    confidence=0.91,
                    reason="discount question",
                    requires_rag=True,
                ),
                "classifier-only discount",
                "promotion_policy",
                WorkflowAction.REPLY,
            ),
            (
                IntentClassification(
                    intent="sensitive_user_safety",
                    domain="sensitive_user_safety",
                    confidence=0.91,
                    reason="safety question",
                    requires_rag=True,
                ),
                "classifier-only safety",
                "sensitive_user_safety",
                WorkflowAction.REPLY,
            ),
        ]
        for classification, message, intent, action in cases:
            engine = InternalWorkflowEngine(intent_classifier=SpyIntentClassifier(classification), rag_retriever=SpyRAGRetriever([]))

            result = await _run(message, engine=engine)

            assert result.intent == intent
            assert result.action == action
            assert result.trace.get("unsupported_intent_fallback") is not True
            assert result.reason != "unsupported_classifier_intent_fallback"

    asyncio.run(scenario())


def test_product_rag_answer_generator_error_uses_safe_reply_without_pending_human():
    async def scenario():
        rag = SpyRAGRetriever([_rag_hit("product_catalog")])
        generator = EmptyAnswerGenerator()
        engine = InternalWorkflowEngine(rag_retriever=rag, answer_generator=generator)

        result = await _run("这个有什么规格", engine=engine, goods_context={"goods_id": "mini-balm", "goods_name": "Mini Balm"})

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "product_basic"
        assert result.reason == "answer_generator_safe_fallback"
        assert "商品页面" in result.reply_text
        assert result.trace["answer_generator_called"] is True
        assert result.trace["answer_error_type"] == "answer_generator_provider_disconnected"
        assert result.trace["answer_error_raw_type"] == "URLError"
        assert result.trace["answer_failure_policy"] == "safe_fallback_reply"
        assert result.trace["answer_fallback_reason"] == "answer_generator_safe_fallback"
        assert result.trace["sets_pending_human"] is False
        assert result.trace.get("transfer_reason", "") == ""
        assert "answer_generator_provider_disconnected" in result.risk_flags

    asyncio.run(scenario())


def test_product_rag_empty_answer_uses_safe_reply_without_pending_human():
    async def scenario():
        rag = SpyRAGRetriever([_rag_hit("product_catalog")])
        generator = EmptyAnswerGenerator(raw_error_type="empty_answer", raw_error_summary="provider returned no answer text")
        engine = InternalWorkflowEngine(rag_retriever=rag, answer_generator=generator)

        result = await _run("这个多少钱", engine=engine, goods_context={"goods_id": "mini-balm", "goods_name": "Mini Balm"})

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "product_basic"
        assert result.reason == "answer_generator_safe_fallback"
        assert result.trace["answer_error_type"] == "answer_generator_empty_answer"
        assert result.trace["answer_empty_reason"] == "provider_returned_empty_text"
        assert result.trace["answer_failure_policy"] == "safe_fallback_reply"
        assert result.trace["sets_pending_human"] is False

    asyncio.run(scenario())


def test_product_card_message_ack_does_not_require_answer_generator_or_pending_human():
    async def scenario():
        generator = EmptyAnswerGenerator()
        engine = InternalWorkflowEngine(answer_generator=generator)

        result = await _run(
            "商品：Mini Balm，价格：99，商品ID：mini-balm",
            engine=engine,
            message_type="64",
            metadata={"goods_id": "mini-balm", "goods_name": "Mini Balm", "message_type": 64},
        )

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "product_basic"
        assert result.reason == "product_card_context_ack"
        assert generator.calls == []
        assert result.trace["message_has_product_card"] is True
        assert result.trace["answer_generator_called"] is False
        assert result.trace["answer_generation_status"] == "not_required"
        assert result.trace["answer_failure_policy"] == "not_required"
        assert result.trace["sets_pending_human"] is False

    asyncio.run(scenario())


def test_sensitive_answer_generator_error_uses_safe_template_without_skip():
    async def scenario():
        classifier = SpyIntentClassifier(
            IntentClassification(
                intent="sensitive_user_safety",
                domain="sensitive_user_safety",
                confidence=0.91,
                reason="safety question",
                requires_rag=True,
            )
        )
        rag = SpyRAGRetriever([_rag_hit("sensitive_user_safety", source_type="sop")])
        generator = EmptyAnswerGenerator(raw_error_type="RemoteDisconnected", raw_error_summary="provider disconnected")
        engine = InternalWorkflowEngine(intent_classifier=classifier, rag_retriever=rag, answer_generator=generator)

        result = await _run("孕妇能用吗", engine=engine)

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "sensitive_user_safety"
        assert result.reason == "answer_generator_safe_template"
        assert result.reply_text
        assert "一定能用" not in result.reply_text
        assert "绝对安全" not in result.reply_text
        assert result.trace["answer_error_type"] == "answer_generator_provider_disconnected"
        assert result.trace["answer_failure_policy"] == "safe_template_reply"
        assert result.trace["sets_pending_human"] is False

    asyncio.run(scenario())


def test_after_sales_answer_generator_error_uses_evidence_template_without_promises():
    async def scenario():
        classifier = SpyIntentClassifier(
            IntentClassification(
                intent="after_sales_evidence_collection",
                domain="after_sales_evidence",
                confidence=0.91,
                reason="damaged item",
                requires_rag=True,
                should_request_evidence=True,
            )
        )
        rag = SpyRAGRetriever([_rag_hit("after_sales_evidence", source_type="sop")])
        generator = EmptyAnswerGenerator(raw_error_type="TimeoutError", raw_error_summary="provider timeout")
        engine = InternalWorkflowEngine(intent_classifier=classifier, rag_retriever=rag, answer_generator=generator)

        result = await _run("收到破损了怎么办", engine=engine)

        assert result.action == WorkflowAction.REQUEST_EVIDENCE
        assert result.intent == "after_sales_evidence_collection"
        assert result.reason == "answer_generator_safe_template"
        assert "照片" in result.reply_text
        assert "赔偿" not in result.reply_text
        assert "补发" not in result.reply_text
        assert result.trace["answer_error_type"] == "answer_generator_timeout"
        assert result.trace["answer_failure_policy"] == "safe_template_reply"
        assert result.trace["sets_pending_human"] is False

    asyncio.run(scenario())


def test_after_sales_keywords_win_over_product_card_ack():
    async def scenario():
        rag = SpyRAGRetriever([_rag_hit("after_sales_evidence", source_type="sop")])
        generator = SpyAnswerGenerator(text="亲，麻烦提供破损照片、外包装照片和订单信息。")
        engine = InternalWorkflowEngine(rag_retriever=rag, answer_generator=generator)

        result = await _run(
            "我这个香水都破了",
            engine=engine,
            goods_context={"goods_id": "goods-1", "goods_name": "香水", "status": "resolved"},
            metadata={"product_context": {"goods_id": "goods-1", "goods_name": "香水", "status": "resolved"}},
        )

        assert result.intent == "after_sales_evidence_collection"
        assert result.action == WorkflowAction.REQUEST_EVIDENCE
        assert rag.calls[0]["domain"] == "after_sales_evidence"
        assert result.trace["rag_hit_count"] == 1

    asyncio.run(scenario())


def test_refund_request_with_product_context_routes_to_after_sales_policy():
    async def scenario():
        rag = SpyRAGRetriever([_rag_hit("after_sales_evidence", source_type="sop")])
        generator = SpyAnswerGenerator(text="亲，退款需要先核实凭证，麻烦提供问题照片和订单信息。")
        engine = InternalWorkflowEngine(rag_retriever=rag, answer_generator=generator)

        result = await _run(
            "赶紧给我退款",
            engine=engine,
            goods_context={"goods_id": "goods-1", "goods_name": "香水", "status": "resolved"},
            metadata={"product_context": {"goods_id": "goods-1", "goods_name": "香水", "status": "resolved"}},
        )

        assert result.intent == "after_sales_evidence_collection"
        assert rag.calls[0]["domain"] == "after_sales_evidence"
        assert result.trace["rag_status"] == "hit"

    asyncio.run(scenario())


def test_short_followup_keeps_recent_after_sales_context_for_rag():
    async def scenario():
        rag = SpyRAGRetriever([_rag_hit("after_sales_evidence", source_type="sop")])
        generator = SpyAnswerGenerator(text="亲，麻烦补充破损照片和外包装照片。")
        engine = InternalWorkflowEngine(rag_retriever=rag, answer_generator=generator)
        context = _context(
            "？",
            goods_context={"goods_id": "goods-1", "goods_name": "香水", "status": "resolved"},
            metadata={"product_context": {"goods_id": "goods-1", "goods_name": "香水", "status": "resolved"}},
        )
        context.history = [
            {"role": "buyer", "content": "我这个香水都破了"},
            {"role": "assistant", "content": "亲，麻烦提供问题照片。"},
        ]

        result = await engine.run(context)

        assert result.intent == "after_sales_evidence_collection"
        assert rag.calls[0]["domain"] == "after_sales_evidence"
        assert "我这个香水都破了" in rag.calls[0]["query"]

    asyncio.run(scenario())


def test_classifier_redline_validation_transfers_to_human():
    async def scenario():
        classifier = SpyIntentClassifier(
            IntentClassification(intent="product_basic", confidence=0.92, reason="bad_classifier", risk_flags=["redline"])
        )
        engine = InternalWorkflowEngine(intent_classifier=classifier)

        result = await _run("ordinary text", engine=engine)

        assert result.action == WorkflowAction.TRANSFER_HUMAN
        assert result.intent == "human_escalation_redline"
        assert "redline" in result.risk_flags

    asyncio.run(scenario())


def test_guardrail_applies_to_internal_product_reply():
    async def scenario():
        classifier = SpyIntentClassifier(
            IntentClassification(intent="product_basic", confidence=0.91, reason="classifier_product")
        )
        repository = FakeProductKnowledgeRepository(
            [{"shop_id": "shop-1", "domain": "product_catalog", "goods_name": "Mini Balm", "usage_method": "we will compensate you today"}]
        )
        engine = InternalWorkflowEngine(
            knowledge_repository=repository,
            intent_classifier=classifier,
            answer_generator=SpyAnswerGenerator(text="We will compensate you today."),
        )

        result = await _run("tell me", engine=engine, goods_context={"goods_name": "Mini Balm"})

        assert result.action == WorkflowAction.TRANSFER_HUMAN
        assert result.reason == "output_guardrail_policy_violation"
        assert "policy_violation" in result.risk_flags
        assert "compensation" in result.risk_flags

    asyncio.run(scenario())


def test_pending_human_and_redline_do_not_call_rag():
    async def scenario():
        rag = SpyRAGRetriever([_rag_hit()])
        pending = await _run(
            _keyword("_PRODUCT_BASIC_KEYWORDS"),
            engine=InternalWorkflowEngine(
                rag_retriever=rag,
                conversation_context_repository=_conversation_repo(pending_human=True),
            ),
        )
        redline = await _run(_keyword("_REDLINE_KEYWORDS", 3), engine=InternalWorkflowEngine(rag_retriever=rag))

        assert pending.action == WorkflowAction.TRANSFER_HUMAN
        assert redline.action == WorkflowAction.TRANSFER_HUMAN
        assert rag.calls == []

    asyncio.run(scenario())


def test_product_basic_rag_hit_wins_before_product_repository():
    async def scenario():
        rag = SpyRAGRetriever([_rag_hit("product_catalog")])
        repository = FakeStatsProductKnowledgeRepository(
            [{"shop_id": "shop-1", "domain": "product_catalog", "goods_name": "Mini Balm", "usage_method": "Use"}]
        )
        engine = InternalWorkflowEngine(
            rag_retriever=rag,
            knowledge_repository=repository,
            answer_generator=SpyAnswerGenerator(text="亲，这款商品信息请以商品页面为准。"),
        )

        result = await _run(_keyword("_PRODUCT_BASIC_KEYWORDS"), engine=engine, goods_context={"goods_name": "Mini Balm"})

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "product_basic"
        assert result.reason == "rag_answer_generated"
        assert result.trace["rag_enabled"] is True
        assert result.trace["rag_status"] == "hit"
        assert result.trace["rag_hit_count"] == 1
        assert result.trace["knowledge_source"] == "rag"
        assert result.trace["knowledge_version"] == "rag-v1"
        assert repository.calls == []

    asyncio.run(scenario())


def test_product_context_is_resolved_from_history_product_anchor_for_rag():
    async def scenario():
        rag = SpyRAGRetriever([_rag_hit("product_catalog")])
        generator = SpyAnswerGenerator(text="亲，这款价格以商品页和结算页为准。")
        engine = InternalWorkflowEngine(rag_retriever=rag, answer_generator=generator)
        context = _context("这个多少钱")
        context.history = [
            {
                "role": "user",
                "content": "商品：Mini Balm，价格：99，商品ID：mini-balm",
                "message_type": "64",
            }
        ]

        result = await engine.run(context)

        assert result.action == WorkflowAction.REPLY
        assert result.reason == "rag_answer_generated"
        assert result.trace["product_context_status"] == "resolved"
        assert result.trace["product_context_source"] == "history"
        assert result.trace["product_context_inherited"] is True
        assert result.trace["product_anchor_source"] == "history"
        assert result.trace["retrieval_mode"] in {"hybrid", "exact"}
        assert rag.calls
        assert "mini-balm" in rag.calls[0]["query"]
        assert generator.calls

    asyncio.run(scenario())


def test_product_hybrid_rag_combines_fulltext_and_semantic_hits():
    store = InMemoryVectorStore()
    embedding = FakeEmbeddingClient(dimension=8, model="fake")
    exact = KnowledgeChunk(
        chunk_id="exact",
        shop_id="shop-1",
        domain="product_catalog",
        source_type="product",
        source_id="goods-1",
        title="Exact Product",
        content="Exact product price boundary.",
        version="product-v1",
        metadata={"goods_id": "goods-1", "goods_name": "Exact Product"},
    )
    semantic = KnowledgeChunk(
        chunk_id="semantic",
        shop_id="shop-1",
        domain="product_catalog",
        source_type="product",
        source_id="goods-2",
        title="Semantic Product",
        content="这个多少钱 semantic similar product.",
        version="product-v1",
        metadata={"goods_id": "goods-2", "goods_name": "Semantic Product"},
    )
    store.upsert(exact, [0.0] * 8, embedding_model="fake")
    store.upsert(semantic, embedding.embed("这个多少钱").vector, embedding_model="fake")
    retriever = VectorStoreRAGRetriever(embedding_client=embedding, vector_store=store, version="product-v1")
    context = _context("这个多少钱", goods_context={"goods_id": "goods-1", "goods_name": "Exact Product"})

    hits = retriever.retrieve(context, "product_basic", "product_catalog", "这个多少钱 Exact Product goods-1", top_k=3)
    stats = retriever.get_last_stats()

    assert hits[0].source_id == "goods-1"
    assert stats["retrieval_mode"] == "hybrid"
    assert stats["fulltext_hit_count"] >= 1
    assert stats["semantic_hit_count"] >= 1


def test_product_basic_rag_empty_falls_back_to_product_repository():
    async def scenario():
        rag = SpyRAGRetriever([])
        repository = FakeStatsProductKnowledgeRepository(
            [{"shop_id": "shop-1", "domain": "product_catalog", "goods_name": "Mini Balm", "usage_method": "Use"}]
        )
        engine = InternalWorkflowEngine(
            rag_retriever=rag,
            knowledge_repository=repository,
            answer_generator=SpyAnswerGenerator(text="亲，这款商品信息请以商品页面为准。"),
        )

        result = await _run(_keyword("_PRODUCT_BASIC_KEYWORDS"), engine=engine, goods_context={"goods_name": "Mini Balm"})

        assert result.action == WorkflowAction.REPLY
        assert result.reason == "product_answer_generated"
        assert result.trace["rag_status"] == "empty"
        assert result.trace["knowledge_source"] == "repository"
        assert repository.calls == ["shop-1"]

    asyncio.run(scenario())


def test_logistics_rag_hit_uses_rag_summary_path():
    async def scenario():
        rag = SpyRAGRetriever([_rag_hit("logistics_policy")])
        engine = InternalWorkflowEngine(
            rag_retriever=rag,
            answer_generator=SpyAnswerGenerator(text="亲，物流以订单物流页为准。"),
        )

        result = await _run(_keyword("_LOGISTICS_KEYWORDS"), engine=engine)

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "logistics_order_status"
        assert result.reason == "rag_policy_answer_generated"
        assert result.trace["rag_domains"] == ["logistics_policy"]
        assert result.trace["knowledge_source"] == "rag"
        assert result.knowledge_refs[0]["source"] == "rag"

    asyncio.run(scenario())


def test_internal_engine_trace_includes_stage_timing_breakdown():
    async def scenario():
        rag = SpyRAGRetriever([_rag_hit("product_catalog")])
        generator = SpyAnswerGenerator(text="亲亲，这款价格以商品页和结算页为准哦。")
        engine = InternalWorkflowEngine(rag_retriever=rag, answer_generator=generator)

        result = await _run(
            _keyword("_PRODUCT_BASIC_KEYWORDS"),
            engine=engine,
            goods_context={"goods_id": "mini-balm", "goods_name": "Mini Balm"},
        )

        timings = result.trace.get("stage_timing")
        assert isinstance(timings, dict)
        expected_keys = {
            "context_build_ms",
            "history_load_ms",
            "product_context_ms",
            "keyword_classify_ms",
            "llm_classify_ms",
            "rag_query_build_ms",
            "embedding_ms",
            "vector_search_ms",
            "rag_total_ms",
            "prompt_build_ms",
            "llm_answer_ms",
            "guardrail_ms",
            "internal_total_ms",
        }
        assert expected_keys.issubset(timings.keys())
        for key in expected_keys:
            assert result.trace[key] == timings[key]
            assert isinstance(timings[key], int)
            assert timings[key] >= 0

        assert timings["rag_total_ms"] >= 0
        assert timings["llm_answer_ms"] >= 0
        assert result.trace["answer_generation_status"] == "ok"

    asyncio.run(scenario())


def test_rag_generated_dangerous_reply_is_guardrailed():
    async def scenario():
        generator = SpyAnswerGenerator(text="We will compensate you today.")
        rag = SpyRAGRetriever([_rag_hit("product_catalog")])
        engine = InternalWorkflowEngine(rag_retriever=rag, answer_generator=generator)

        result = await _run(
            _keyword("_PRODUCT_BASIC_KEYWORDS"),
            engine=engine,
            goods_context={"goods_name": "Mini Balm"},
        )

        assert result.action == WorkflowAction.TRANSFER_HUMAN
        assert result.reason == "output_guardrail_policy_violation"
        assert "policy_violation" in result.risk_flags
        assert result.trace["rag_hit_count"] == 1

    asyncio.run(scenario())


def test_sop_provider_hit_fills_sop_version_and_summary_trace():
    async def scenario():
        provider = FakeSOPProvider(
            [{"shop_id": "shop-1", "domain": "promotion_policy", "version": "sop-2026.05", "id": "sop-safe-id"}]
        )
        engine = InternalWorkflowEngine(sop_provider=provider)

        result = await _run(_keyword("_PROMOTION_KEYWORDS"), engine=engine)

        assert result.trace["workflow_version"] == "internal-v1"
        assert result.trace["sop_version"] == "sop-2026.05"
        assert result.trace["sop_domains"] == ["promotion_policy"]
        assert result.trace["sop_record_count"] == 1

    asyncio.run(scenario())


def test_unmatched_message_falls_back_without_customerized_reply():
    async def scenario():
        result = await _run("hello")

        assert result.action == WorkflowAction.FALLBACK
        assert result.intent == "fallback"
        assert result.reason == "no_rule_matched"
        assert not result.reply_text

    asyncio.run(scenario())


def test_unmatched_message_uses_answer_generator_when_available():
    async def scenario():
        generator = SpyAnswerGenerator(text="亲亲，请问您想咨询商品、物流还是售后呢？")
        engine = InternalWorkflowEngine(answer_generator=generator)

        result = await _run("?", engine=engine)

        assert result.action == WorkflowAction.REPLY
        assert result.intent == "fallback"
        assert result.reply_text == "亲亲，请问您想咨询商品、物流还是售后呢？"
        assert generator.calls
        assert result.trace["answer_generator_called"] is True
        assert result.trace["answer_generation_status"] == "ok"

    asyncio.run(scenario())


def test_internal_trace_uses_length_and_hash_not_plain_content():
    async def scenario():
        content = _keyword("_REDLINE_KEYWORDS")
        result = await _run(content)

        assert result.trace["content_length"] == len(content)
        assert result.trace["content_hash"]
        assert content not in repr(result.trace)

    asyncio.run(scenario())
def test_product_answer_calibration_includes_raw_price_when_llm_is_too_conservative():
    async def scenario():
        hit = RetrievalHit(
            chunk_id="price-hit",
            shop_id="shop-1",
            domain="product_catalog",
            title="Mini Balm",
            content_summary="price [raw]: 19.70-29.60\nprice_note [manual_override]: 价格以页面和结算页显示为准。",
            score=0.9,
            source_type="product",
            source_id="mini-balm",
            version="active-v1",
            content_hash="price-hash",
            metadata={"version_id": 5},
        )
        engine = InternalWorkflowEngine(
            rag_retriever=SpyRAGRetriever([hit]),
            answer_generator=SpyAnswerGenerator(text="\u4eb2\u4eb2\uff0c\u4ef7\u683c\u4ee5\u5546\u54c1\u9875\u9762\u548c\u7ed3\u7b97\u9875\u663e\u793a\u4e3a\u51c6\u54e6\u3002"),
        )

        result = await _run("\u8fd9\u4e2a\u591a\u5c11\u94b1", engine=engine, goods_context={"goods_id": "mini-balm", "goods_name": "Mini Balm"})

        assert result.action == WorkflowAction.REPLY
        assert "19.70-29.60" in result.reply_text
        assert "\u7ed3\u7b97\u9875" in result.reply_text
        assert "\u79c1\u4e0b\u4f18\u60e0" not in result.reply_text
        assert result.trace["answer_calibrated"] is True
    asyncio.run(scenario())


def test_product_answer_calibration_includes_specs_when_llm_is_too_conservative():
    async def scenario():
        hit = RetrievalHit(
            chunk_id="spec-hit",
            shop_id="shop-1",
            domain="product_catalog",
            title="Mini Balm",
            content_summary="specs [raw]: ['款式: 一瓶', '款式: 两瓶']",
            score=0.9,
            source_type="product",
            source_id="mini-balm",
            version="active-v1",
            content_hash="spec-hash",
            metadata={"version_id": 5},
        )
        engine = InternalWorkflowEngine(
            rag_retriever=SpyRAGRetriever([hit]),
            answer_generator=SpyAnswerGenerator(text="\u4eb2\u4eb2\uff0c\u89c4\u683c\u4ee5\u5546\u54c1\u9875\u9762\u663e\u793a\u4e3a\u51c6\u54e6\u3002"),
        )

        result = await _run("\u8fd9\u4e2a\u4ec0\u4e48\u89c4\u683c", engine=engine, goods_context={"goods_id": "mini-balm", "goods_name": "Mini Balm"})

        assert "\u4e00\u74f6" in result.reply_text
        assert "\u4e24\u74f6" in result.reply_text
        assert "\u5546\u54c1\u9875\u9762" in result.reply_text
        assert result.trace["answer_calibrated"] is True
    asyncio.run(scenario())


def test_product_answer_calibration_prioritizes_usage_override_when_llm_is_too_conservative():
    async def scenario():
        hit = RetrievalHit(
            chunk_id="usage-hit",
            shop_id="shop-1",
            domain="product_catalog",
            title="Mini Balm",
            content_summary="usage [manual_override]: 请按商品页面说明使用；如页面有用量或步骤说明，以商品详情页为准。",
            score=0.9,
            source_type="product",
            source_id="mini-balm",
            version="active-v1",
            content_hash="usage-hash",
            metadata={"version_id": 5},
        )
        engine = InternalWorkflowEngine(
            rag_retriever=SpyRAGRetriever([hit]),
            answer_generator=SpyAnswerGenerator(text="\u4f7f\u7528\u65b9\u6cd5\u8bf7\u4ee5\u5546\u54c1\u8be6\u60c5\u9875\u8bf4\u660e\u4e3a\u51c6\u54e6\u3002"),
        )

        result = await _run("\u8fd9\u4e2a\u600e\u4e48\u7528", engine=engine, goods_context={"goods_id": "mini-balm", "goods_name": "Mini Balm"})

        assert "\u6309\u5546\u54c1\u9875\u9762\u8bf4\u660e\u4f7f\u7528" in result.reply_text
        assert "\u5546\u54c1\u8be6\u60c5\u9875" in result.reply_text
        assert result.trace["answer_calibrated"] is True
    asyncio.run(scenario())
