import asyncio
from types import SimpleNamespace

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from Message.core.pipeline import MessagePipeline
from Message.workflow.answer_generator import OpenAICompatibleAnswerGenerator
from Message.workflow.fastgpt_engine import FastGPTWorkflowEngine
from Message.workflow.internal_engine import InternalWorkflowEngine
from Message.workflow.llm_classifier import OpenAICompatibleIntentClassifier
from Message.workflow.router import create_ai_workflow_engine, get_ai_workflow_backend
from Message.workflow.types import WorkflowAction, WorkflowContext


class FakeFastGPT:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.reset_calls = []
        self.fallback_calls = []
        self.should_transfer_calls = []

    def call(self, messages, dataset_id, **kwargs):
        self.calls.append((messages, dataset_id, kwargs))
        return self.result

    def reset_failures(self, session_id):
        self.reset_calls.append(session_id)

    def contains_transfer_intent(self, reply_text):
        return "manual-transfer" in str(reply_text)

    def get_fallback(self, session_id, already_failed=False):
        self.fallback_calls.append((session_id, already_failed))
        return "fallback reply"

    def should_transfer(self, session_id):
        self.should_transfer_calls.append(session_id)
        return False


class FakeDb:
    def __init__(self, dataset_id="dataset-1"):
        self.dataset_id = dataset_id

    def get_shop_by_platform_id(self, platform, shop_platform_id):
        return {
            "id": "shop-db-1",
            "shop_id": shop_platform_id,
            "shop_name": "shop-name",
            "fastgpt_dataset_id": self.dataset_id,
        }


class FakeConversation:
    session_id = "session-1"
    status = "active"


class FakeSessionManager:
    def __init__(self):
        self.messages = []
        self.statuses = []
        self.fallback_marks = []

    async def get_or_create_conversation(self, shop_id, buyer_id, user_id):
        return FakeConversation()

    def add_message(self, session_id, role, content):
        self.messages.append((session_id, role, content))

    def set_status(self, session_id, status):
        self.statuses.append((session_id, status))

    def build_context_messages(self, session_id, shop_name, system_prompt, buyer_text, cached_products):
        return [{"role": "user", "content": buyer_text}]

    def reset_fallback_state(self, session_id):
        self.fallback_marks.append((session_id, "reset"))

    def should_send_fallback(self, session_id):
        return "first"

    def mark_fallback_sent(self, session_id, stage):
        self.fallback_marks.append((session_id, stage))

    def get_fallback_state(self, session_id):
        return {}

    async def check_and_compress(self, session_id):
        return None


class FakeKeywordHandler:
    def check(self, shop_id, text):
        return {"matched": False}


def _workflow_context(content="hello"):
    return WorkflowContext(
        trace_id="trace-1",
        shop_id="shop-1",
        user_id="user-1",
        customer_uid="buyer-1",
        buyer_id="buyer-1",
        session_id="session-1",
        chat_id="chat-1",
        dataset_id="dataset-1",
        message_type="text",
        content=content,
        messages=[{"role": "user", "content": content}],
        metadata={"shop_name": "shop-name"},
    )


def _pipeline_message():
    return {
        "buyer_id": "buyer-1",
        "shop_platform_id": "shop-1",
        "content": "buyer question",
        "user_id": "user-1",
        "trace_id": "trace-1",
        "source_message_id": "source-1",
        "queue_message_id": "queue-1",
        "message_type": "text",
    }


def test_default_backend_is_internal(monkeypatch):
    monkeypatch.delenv("AI_WORKFLOW_BACKEND", raising=False)

    assert get_ai_workflow_backend() == "internal"
    assert isinstance(create_ai_workflow_engine(fastgpt_handler=FakeFastGPT({})), InternalWorkflowEngine)


def test_backend_router_selects_fastgpt(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_BACKEND", "fastgpt")

    engine = create_ai_workflow_engine(fastgpt_handler=FakeFastGPT({}))

    assert isinstance(engine, FastGPTWorkflowEngine)


def test_backend_router_selects_internal(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_BACKEND", "internal")
    monkeypatch.delenv("AI_WORKFLOW_ANSWER_GENERATOR", raising=False)
    monkeypatch.delenv("AI_WORKFLOW_INTENT_CLASSIFIER", raising=False)

    engine = create_ai_workflow_engine(fastgpt_handler=FakeFastGPT({}))

    assert isinstance(engine, InternalWorkflowEngine)
    assert engine.knowledge_repository is not None
    assert engine.answer_generator is None


def test_backend_router_selects_explicit_internal_real_llm_components(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_BACKEND", "internal")
    monkeypatch.setenv("AI_WORKFLOW_ANSWER_GENERATOR", "openai_compatible")
    monkeypatch.setenv("AI_WORKFLOW_INTENT_CLASSIFIER", "openai_compatible")
    monkeypatch.setenv("AI_WORKFLOW_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("AI_WORKFLOW_LLM_MODEL", "test-model")
    monkeypatch.setenv("AI_WORKFLOW_LLM_API_KEY_ENV", "AI_WORKFLOW_TEST_LLM_KEY")

    engine = create_ai_workflow_engine(fastgpt_handler=FakeFastGPT({}))

    assert isinstance(engine, InternalWorkflowEngine)
    assert isinstance(engine.answer_generator, OpenAICompatibleAnswerGenerator)
    assert isinstance(engine.intent_classifier, OpenAICompatibleIntentClassifier)


def test_backend_router_accepts_use_real_llm_aliases(monkeypatch):
    monkeypatch.setenv("AI_WORKFLOW_BACKEND", "internal")
    monkeypatch.delenv("AI_WORKFLOW_ANSWER_GENERATOR", raising=False)
    monkeypatch.delenv("AI_WORKFLOW_INTENT_CLASSIFIER", raising=False)
    monkeypatch.setenv("AI_WORKFLOW_USE_REAL_ANSWER_GENERATOR", "1")
    monkeypatch.setenv("AI_WORKFLOW_USE_REAL_INTENT_CLASSIFIER", "1")
    monkeypatch.setenv("AI_WORKFLOW_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("AI_WORKFLOW_LLM_MODEL", "test-model")
    monkeypatch.setenv("AI_WORKFLOW_LLM_API_KEY_ENV", "AI_WORKFLOW_TEST_LLM_KEY")

    engine = create_ai_workflow_engine(fastgpt_handler=FakeFastGPT({}))

    assert isinstance(engine, InternalWorkflowEngine)
    assert isinstance(engine.answer_generator, OpenAICompatibleAnswerGenerator)
    assert isinstance(engine.intent_classifier, OpenAICompatibleIntentClassifier)


def test_fastgpt_workflow_engine_success_returns_reply():
    async def scenario():
        fastgpt = FakeFastGPT({"success": True, "content": "AI reply", "tokens": 3})
        engine = FastGPTWorkflowEngine(fastgpt)

        result = await engine.run(_workflow_context())

        assert result.action == WorkflowAction.REPLY
        assert result.reply_text == "AI reply"
        assert result.trace["tokens"] == 3
        assert fastgpt.calls[0][1] == "dataset-1"
        assert fastgpt.calls[0][2]["chat_id"] == "chat-1"

    asyncio.run(scenario())


def test_fastgpt_workflow_engine_failure_returns_sanitized_fallback():
    async def scenario():
        bearer_value = "Be" + "arer abc123"
        ark_value = "ar" + "k-example-value"
        fastgpt = FakeFastGPT(
            {
                "success": False,
                "content": None,
                "error": f"provider rejected credential {bearer_value} and {ark_value}",
            }
        )
        engine = FastGPTWorkflowEngine(fastgpt)

        result = await engine.run(_workflow_context())

        assert result.action == WorkflowAction.FALLBACK
        assert result.raw_error_type == "FastGPTFailure"
        assert "abc123" not in result.raw_error_summary
        assert "ark-example-value" not in result.raw_error_summary

    asyncio.run(scenario())


def test_internal_workflow_engine_skeleton_rules():
    async def scenario():
        engine = InternalWorkflowEngine()

        transfer = await engine.run(_workflow_context("我要投诉并要求赔偿"))
        evidence = await engine.run(_workflow_context("收到破损了"))
        clarification = await engine.run(_workflow_context("这个怎么用"))

        assert transfer.action == WorkflowAction.TRANSFER_HUMAN
        assert evidence.action == WorkflowAction.REQUEST_EVIDENCE
        assert clarification.action == WorkflowAction.REPLY
        assert clarification.intent == "ask_product_clarification"

    asyncio.run(scenario())


def test_pipeline_uses_workflow_engine_for_ai_reply():
    async def scenario():
        fastgpt = FakeFastGPT({"success": True, "content": "pipeline ai reply", "tokens": 2})
        pipeline = MessagePipeline(
            FakeDb(),
            FakeSessionManager(),
            FakeKeywordHandler(),
            fastgpt,
            None,
            workflow_engine=FastGPTWorkflowEngine(fastgpt),
        )

        result = await pipeline.process(_pipeline_message())

        assert result["action"] == "reply"
        assert result["text"] == "pipeline ai reply"
        assert fastgpt.calls

    asyncio.run(scenario())


def test_pipeline_preserves_fastgpt_failure_fallback_behavior():
    async def scenario():
        fastgpt = FakeFastGPT({"success": False, "content": None, "error": "timeout"})
        session_manager = FakeSessionManager()
        pipeline = MessagePipeline(
            FakeDb(),
            session_manager,
            FakeKeywordHandler(),
            fastgpt,
            None,
            workflow_engine=FastGPTWorkflowEngine(fastgpt),
        )

        result = await pipeline.process(_pipeline_message())

        assert result["action"] == "reply"
        assert result["text"] == "fallback reply"
        assert ("session-1", "pending_human") in session_manager.statuses
        assert fastgpt.fallback_calls == [("session-1", True)]

    asyncio.run(scenario())


def test_pipeline_preserves_ai_transfer_human_behavior():
    async def scenario():
        fastgpt = FakeFastGPT({"success": True, "content": "manual-transfer", "tokens": 1})
        session_manager = FakeSessionManager()
        pipeline = MessagePipeline(
            FakeDb(),
            session_manager,
            FakeKeywordHandler(),
            fastgpt,
            None,
            workflow_engine=FastGPTWorkflowEngine(fastgpt),
        )

        result = await pipeline.process(_pipeline_message())

        assert result["action"] == "transfer_human"
        assert result["session_id"] == "session-1"
        assert ("session-1", "pending_human") in session_manager.statuses

    asyncio.run(scenario())
