import asyncio
import json
import time
from types import SimpleNamespace

import Session.session_manager as session_module
from bridge.context import ContextType
from Message.core.pipeline import MessagePipeline
from Message.core.queue import queue_manager
from Message.handlers.ai_handler import AIReplyHandler
from Message.workflow.fastgpt_engine import FastGPTWorkflowEngine
from Message.workflow.types import WorkflowAction, WorkflowResult
from Session.session_manager import SessionManager
from ui.auto_reply.manager import AutoReplyManager


class FakeNotificationService:
    def __init__(self):
        self.alerts = []

    def alert_human_fallback(self, shop_id, user_id, reason, alert_level="low", metadata=None):
        alert = {
            "shop_id": shop_id,
            "user_id": user_id,
            "reason": reason,
            "alert_level": alert_level,
        }
        if metadata is not None:
            alert["metadata"] = metadata
        self.alerts.append(alert)


class BlockingFastGPT:
    def call(self, *args, **kwargs):
        time.sleep(0.2)
        return {"success": True, "content": "ok", "tokens": 1}


class SkipPipeline:
    async def process(self, message, **kwargs):
        return {"action": "skip", "session_id": "s1", "status": "pending_human"}


class BlockPipeline:
    def __init__(self):
        self.calls = 0

    async def process(self, message, **kwargs):
        self.calls += 1
        return {"action": "block", "session_id": "s1"}


class CountingPipeline:
    def __init__(self):
        self.calls = 0

    async def process(self, message, **kwargs):
        self.calls += 1
        return {"action": "reply", "text": "pipeline-reply", "session_id": "s1"}


class OutcomePipeline:
    def __init__(self, action, text="ok"):
        self.action = action
        self.text = text

    async def process(self, message, **kwargs):
        return {"action": self.action, "text": self.text, "session_id": "s1"}


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))

    def debug(self, message):
        self.messages.append(("debug", message))


class FakePipelineDb:
    def get_shop_by_platform_id(self, platform, shop_platform_id):
        return {
            "id": "db-shop-1",
            "shop_id": shop_platform_id,
            "shop_name": "shop",
            "fastgpt_dataset_id": "dataset-1",
        }


class FakePipelineConversation:
    def __init__(self, session_id="session-1", status="active"):
        self.session_id = session_id
        self.status = status


class FakePipelineSessionManager:
    def __init__(self):
        self.statuses = {}
        self.messages = {}

    async def get_or_create_conversation(self, shop_id, buyer_id, user_id):
        return FakePipelineConversation(session_id=f"{shop_id}:{buyer_id}:{user_id}", status="active")

    def add_message(self, session_id, role, content):
        self.messages.setdefault(session_id, []).append(SimpleNamespace(role=role, content=content))

    def set_status(self, session_id, status):
        self.statuses[session_id] = status

    def reset_fallback_state(self, session_id):
        pass

    def get_fallback_state(self, session_id):
        return {}

    def should_send_fallback(self, session_id):
        return "first"

    def mark_fallback_sent(self, session_id, stage):
        pass

    def build_context_messages(self, session_id, shop_name, system_prompt_template, current_message, cached_products=""):
        return [
            {"role": item.role, "content": item.content}
            for item in self.messages.get(session_id, [])
        ]

    def get_recent_messages(self, session_id, limit=40):
        return list(self.messages.get(session_id, []))[-limit:]

    async def check_and_compress(self, session_id):
        return None


class FakePipelineKeywordHandler:
    def check(self, shop_id, text):
        return {"matched": False}


class FakePipelineFastGpt:
    def __init__(self, transfer_on_text=False):
        self.transfer_on_text = transfer_on_text

    def reset_failures(self, session_id):
        pass

    def contains_transfer_intent(self, reply):
        return bool(self.transfer_on_text and "human" in str(reply).lower())

    def get_fallback(self, session_id, already_failed=False):
        return "fallback"

    def should_transfer(self, session_id):
        return False


class RecordingWorkflowEngine:
    def __init__(self, reply="ok", action=WorkflowAction.REPLY, trace=None):
        self.reply = reply
        self.action = action
        self.trace = trace or {"workflow_version": "internal-v1", "guardrail_status": "safe"}
        self.contexts = []

    async def run(self, context):
        self.contexts.append(context)
        return WorkflowResult(
            action=self.action,
            reply_text=self.reply,
            intent="product_basic",
            reason="test",
            trace=dict(self.trace),
        )


class FakeConfigDb:
    def __init__(self):
        self.values = {}

    def get_config(self, key):
        value = self.values.get(key)
        if value is None:
            return None
        return {"config_key": key, "config_value": value}

    def set_config(self, key, value):
        self.values[key] = value
        return True

    def delete_config(self, key):
        self.values.pop(key, None)
        return True


def _base_context(message_type=ContextType.TEXT, content="hello"):
    return SimpleNamespace(
        type=message_type,
        content=content,
        kwargs=SimpleNamespace(
            from_uid="buyer-1",
            shop_id="shop-1",
            user_id="user-1",
            trace_id="trace-1",
            source_message_id="source-1",
            content_length=len(str(content or "")),
            content_hash="content-hash-1",
        ),
    )


def _base_metadata():
    return {
        "shop_id": "shop-1",
        "user_id": "user-1",
        "from_uid": "buyer-1",
        "trace_id": "trace-1",
        "source_message_id": "source-1",
        "queue_message_id": "queue-1",
    }


def _install_notification_service(service):
    from core.di_container import container
    from core.notification import NotificationService

    container._services.clear()
    container._singletons.clear()
    container._scoped_instances.clear()
    container.register_singleton(NotificationService, instance=service)
    return container


def _clear_container():
    from core.di_container import container

    container._services.clear()
    container._singletons.clear()
    container._scoped_instances.clear()


def test_fastgpt_call_does_not_block_event_loop():
    async def scenario():
        pipeline = MessagePipeline(None, None, None, BlockingFastGPT(), None)
        ticked = False

        async def ticker():
            nonlocal ticked
            await asyncio.sleep(0.05)
            ticked = True

        call_task = asyncio.create_task(
            pipeline._call_fastgpt_async(
                messages=[{"role": "user", "content": "hi"}],
                dataset_id="ds",
                chat_id="chat",
                shop_id="shop",
                shop_name="shop name",
            )
        )
        tick_task = asyncio.create_task(ticker())
        await asyncio.gather(call_task, tick_task)

        assert ticked is True
        assert call_task.result()["content"] == "ok"

    asyncio.run(scenario())


def test_pipeline_skip_is_silent_not_fallback():
    async def scenario():
        handler = AIReplyHandler()
        handler._pipeline = SkipPipeline()

        result = await handler._get_ai_reply(
            "退款",
            SimpleNamespace(content="退款", kwargs=SimpleNamespace()),
        )

        assert result == handler.PIPELINE_SKIP

    asyncio.run(scenario())


def test_pipeline_block_is_processed_without_reply_or_transfer():
    async def scenario():
        handler = AIReplyHandler()
        pipeline = BlockPipeline()
        handler._pipeline = pipeline
        calls = {"send": 0, "transfer": 0, "fallback": 0}
        logger = FakeLogger()

        async def fake_send_reply(context, reply, metadata):
            calls["send"] += 1
            return True

        def fake_alert_manual_transfer(metadata, session_id, reason, alert_level="low"):
            calls["transfer"] += 1

        async def fake_handle_fallback(context, metadata):
            calls["fallback"] += 1
            return False

        handler.logger = logger
        handler._send_reply = fake_send_reply
        handler._alert_manual_transfer = fake_alert_manual_transfer
        handler._handle_fallback = fake_handle_fallback

        context = SimpleNamespace(
            type=ContextType.TEXT,
            content="屏蔽词",
            kwargs=SimpleNamespace(
                from_uid="buyer-1",
                shop_id="shop-1",
                user_id="user-1",
                trace_id="trace-1",
                source_message_id="source-1",
                content_length=3,
                content_hash="hash-1",
            ),
        )
        metadata = {
            "shop_id": "shop-1",
            "user_id": "user-1",
            "from_uid": "buyer-1",
            "trace_id": "trace-1",
            "source_message_id": "source-1",
            "queue_message_id": "queue-1",
        }

        result = await handler.handle(context, metadata)

        assert result is True
        assert pipeline.calls == 1
        assert calls == {"send": 0, "transfer": 0, "fallback": 0}
        assert any(
            "event=pdd.message.skipped" in message and "action=keyword_block" in message
            for _, message in logger.messages
        )

    asyncio.run(scenario())


def test_media_and_empty_messages_have_deterministic_handler_paths():
    async def scenario(message_type, content, expected):
        handler = AIReplyHandler()
        pipeline = CountingPipeline()
        logger = FakeLogger()
        handler._pipeline = pipeline
        handler.logger = logger
        calls = {"send": 0, "transfer": 0, "fallback": 0}
        sent_replies = []

        async def fake_send_reply(context, reply, metadata):
            calls["send"] += 1
            sent_replies.append(reply)
            return True

        def fake_alert_manual_transfer(metadata, session_id, reason, alert_level="low"):
            calls["transfer"] += 1

        async def fake_handle_fallback(context, metadata):
            calls["fallback"] += 1
            return False

        handler._send_reply = fake_send_reply
        handler._alert_manual_transfer = fake_alert_manual_transfer
        handler._handle_fallback = fake_handle_fallback

        context = SimpleNamespace(
            type=message_type,
            content=content,
            kwargs=SimpleNamespace(
                from_uid="buyer-1",
                shop_id="shop-1",
                user_id="user-1",
                trace_id=f"trace-{message_type.value}",
                source_message_id="source-1",
                content_length=len(str(content or "")),
                content_hash="hash-1",
            ),
        )
        metadata = {
            "shop_id": "shop-1",
            "user_id": "user-1",
            "from_uid": "buyer-1",
            "trace_id": f"trace-{message_type.value}",
            "source_message_id": "source-1",
            "queue_message_id": "queue-1",
        }

        result = await handler.handle(context, metadata)

        assert result is True
        assert pipeline.calls == 0
        assert calls == expected["calls"]
        assert any(expected["action"] in message for _, message in logger.messages)
        if expected["send"]:
            assert sent_replies
        else:
            assert sent_replies == []

    asyncio.run(
        scenario(
            ContextType.IMAGE,
            "[图片]",
            {
                "calls": {"send": 1, "transfer": 0, "fallback": 0},
                "action": "action=image_intercept",
                "send": True,
            },
        )
    )
    asyncio.run(
        scenario(
            ContextType.VIDEO,
            "[视频]",
            {
                "calls": {"send": 1, "transfer": 1, "fallback": 0},
                "action": "action=video_intercept",
                "send": True,
            },
        )
    )
    asyncio.run(
        scenario(
            ContextType.EMOTION,
            "[表情]",
            {
                "calls": {"send": 1, "transfer": 0, "fallback": 0},
                "action": "action=emotion_default_reply",
                "send": True,
            },
        )
    )
    asyncio.run(
        scenario(
            ContextType.TEXT,
            "",
            {
                "calls": {"send": 0, "transfer": 0, "fallback": 0},
                "action": "action=empty_content",
                "send": False,
            },
        )
    )
    asyncio.run(
        scenario(
            ContextType.SYSTEM_BIZ,
            "system event",
            {
                "calls": {"send": 0, "transfer": 0, "fallback": 0},
                "action": "action=unsupported_message_type",
                "send": False,
            },
        )
    )


def test_video_intercept_notification_metadata_includes_trace_action():
    async def scenario():
        notifier = FakeNotificationService()
        _install_notification_service(notifier)
        handler = AIReplyHandler()
        handler._pipeline = CountingPipeline()

        async def fake_send_reply(context, reply, metadata):
            return True

        handler._send_reply = fake_send_reply
        try:
            result = await handler.handle(_base_context(ContextType.VIDEO, "[视频]"), _base_metadata())
        finally:
            _clear_container()

        assert result is True
        assert len(notifier.alerts) == 1
        metadata = notifier.alerts[0]["metadata"]
        assert metadata["trace_id"] == "trace-1"
        assert metadata["source_message_id"] == "source-1"
        assert metadata["queue_message_id"] == "queue-1"
        assert metadata["shop_id"] == "shop-1"
        assert metadata["user_id"] == "user-1"
        assert metadata["customer_uid"] == "buyer-1"
        assert metadata["action"] == "video_intercept"
        assert metadata["message_type"] == "video"
        assert metadata["reply_length"] > 0
        assert metadata["reply_hash"]

    asyncio.run(scenario())


def test_send_reply_failure_notification_metadata_has_final_status(monkeypatch):
    async def scenario():
        notifier = FakeNotificationService()
        _install_notification_service(notifier)
        handler = AIReplyHandler()

        class FakeSender:
            def __init__(self, shop_id, user_id):
                pass

            def send_text(self, from_uid, reply):
                return {"success": False, "result": {"error_code": 500}}

        monkeypatch.setattr("Channel.pinduoduo.utils.API.send_message.SendMessage", FakeSender)
        try:
            result = await handler._send_reply(_base_context(ContextType.TEXT, "buyer text"), "reply text", _base_metadata())
        finally:
            _clear_container()

        assert result is False
        assert len(notifier.alerts) == 1
        metadata = notifier.alerts[0]["metadata"]
        assert metadata["trace_id"] == "trace-1"
        assert metadata["action"] == "reply_send_failed"
        assert metadata["final_status"] == "reply_send_failed"
        assert metadata["reply_length"] == len("reply text")
        assert metadata["reply_hash"]
        assert metadata["content_length"] == len("buyer text")
        assert metadata["content_hash"]

    asyncio.run(scenario())


def test_send_reply_writes_private_trace_status(monkeypatch, tmp_path):
    async def scenario():
        monkeypatch.setenv("AI_WORKFLOW_DEBUG_TRACE", "1")
        monkeypatch.setenv("AI_WORKFLOW_DEBUG_TRACE_DIR", str(tmp_path))
        handler = AIReplyHandler()

        class FakeSender:
            def __init__(self, shop_id, user_id):
                pass

            def send_text(self, from_uid, reply):
                return {"success": True, "result": {"result": "ok"}}

        monkeypatch.setattr("Channel.pinduoduo.utils.API.send_message.SendMessage", FakeSender)
        result = await handler._send_reply(_base_context(ContextType.TEXT, "buyer text"), "reply text", _base_metadata())

        assert result is True
        payload = json.loads((tmp_path / "trace-1.json").read_text(encoding="utf-8"))
        events = payload["events"]
        assert events["send_started"]["reply_text"] == "reply text"
        assert events["send_completed"]["final_status"] == "reply_sent"
        assert events["send_completed"]["pdd_send_status"] == "ok"

    asyncio.run(scenario())


def test_send_reply_unknown_delivery_notification_metadata_has_final_status(monkeypatch):
    async def scenario():
        notifier = FakeNotificationService()
        _install_notification_service(notifier)
        handler = AIReplyHandler()

        class FakeSender:
            def __init__(self, shop_id, user_id):
                pass

            def send_text(self, from_uid, reply):
                return {"success": True, "result": "accepted"}

        monkeypatch.setattr("Channel.pinduoduo.utils.API.send_message.SendMessage", FakeSender)
        try:
            result = await handler._send_reply(_base_context(ContextType.TEXT, "buyer text"), "reply text", _base_metadata())
        finally:
            _clear_container()

        assert result is False
        assert len(notifier.alerts) == 1
        metadata = notifier.alerts[0]["metadata"]
        assert metadata["trace_id"] == "trace-1"
        assert metadata["action"] == "reply_delivery_unknown"
        assert metadata["final_status"] == "reply_delivery_unknown"
        assert metadata["reply_length"] == len("reply text")
        assert metadata["reply_hash"]

    asyncio.run(scenario())


def test_reply_send_failed_is_not_logged_as_transfer_human():
    async def scenario():
        handler = AIReplyHandler()
        handler._pipeline = OutcomePipeline("reply", text="reply text")
        logger = FakeLogger()
        handler.logger = logger

        async def fake_send_reply(context, reply, metadata):
            return False

        handler._send_reply = fake_send_reply
        result = await handler.handle(_base_context(ContextType.TEXT, "buyer text"), _base_metadata())

        assert result is True
        joined = "\n".join(message for _, message in logger.messages)
        assert "action=reply_send_failed" in joined
        assert "event=pdd.transfer_human.triggered" not in joined

    asyncio.run(scenario())


def test_transfer_send_failed_is_logged_separately_from_reply_failure():
    async def scenario():
        handler = AIReplyHandler()
        handler._pipeline = OutcomePipeline("transfer_human", text="transfer reply")
        logger = FakeLogger()
        handler.logger = logger

        async def fake_send_reply(context, reply, metadata):
            return False

        handler._send_reply = fake_send_reply
        result = await handler.handle(_base_context(ContextType.TEXT, "buyer text"), _base_metadata())

        assert result is True
        joined = "\n".join(message for _, message in logger.messages)
        assert "action=transfer_send_failed" in joined

    asyncio.run(scenario())


def test_ai_empty_reply_notification_metadata_includes_action():
    async def scenario():
        notifier = FakeNotificationService()
        _install_notification_service(notifier)
        handler = AIReplyHandler()
        handler._pipeline = OutcomePipeline("reply", text="")

        async def fake_handle_fallback(context, metadata):
            return True

        handler._handle_fallback = fake_handle_fallback
        try:
            result = await handler.handle(_base_context(ContextType.TEXT, "buyer text"), _base_metadata())
        finally:
            _clear_container()

        assert result is True
        assert len(notifier.alerts) == 1
        metadata = notifier.alerts[0]["metadata"]
        assert metadata["trace_id"] == "trace-1"
        assert metadata["source_message_id"] == "source-1"
        assert metadata["queue_message_id"] == "queue-1"
        assert metadata["action"] == "ai_empty_reply"
        assert metadata["message_type"] == "text"
        assert metadata["content_length"] == len("buyer text")
        assert metadata["content_hash"]

    asyncio.run(scenario())


def test_pipeline_missing_dataset_notification_metadata_includes_action():
    class FakeDb:
        def get_shop_by_platform_id(self, platform, shop_platform_id):
            return {
                "id": "db-shop-1",
                "shop_id": shop_platform_id,
                "shop_name": "shop",
                "fastgpt_dataset_id": "",
            }

    class FakeSessionManager:
        async def get_or_create_conversation(self, shop_id, buyer_id, user_id):
            return SimpleNamespace(session_id="session-1", status="active")

        def add_message(self, *args, **kwargs):
            pass

        def set_status(self, *args, **kwargs):
            pass

        def build_context_messages(self, *args, **kwargs):
            return []

        async def check_and_compress(self, *args, **kwargs):
            return None

    class FakeKeywordHandler:
        def check(self, shop_id, text):
            return {"matched": False}

    class FakeFastGpt:
        pass

    async def scenario():
        notifier = FakeNotificationService()
        _install_notification_service(notifier)
        pipeline = MessagePipeline(
            FakeDb(),
            FakeSessionManager(),
            FakeKeywordHandler(),
            FakeFastGpt(),
            None,
            workflow_engine=FastGPTWorkflowEngine(FakeFastGpt()),
        )
        try:
            result = await pipeline.process(
                {
                    "buyer_id": "buyer-1",
                    "shop_platform_id": "shop-1",
                    "content": "buyer question",
                    "user_id": "user-1",
                    "trace_id": "trace-1",
                    "source_message_id": "source-1",
                    "queue_message_id": "queue-1",
                    "message_type": "text",
                }
            )
        finally:
            _clear_container()

        assert result["action"] == "transfer_human"
        assert len(notifier.alerts) == 1
        metadata = notifier.alerts[0]["metadata"]
        assert metadata["trace_id"] == "trace-1"
        assert metadata["source_message_id"] == "source-1"
        assert metadata["queue_message_id"] == "queue-1"
        assert metadata["session_id"] == "session-1"
        assert metadata["shop_id"] == "shop-1"
        assert metadata["user_id"] == "user-1"
        assert metadata["customer_uid"] == "buyer-1"
        assert metadata["action"] == "missing_fastgpt_dataset_id"
        assert metadata["message_type"] == "text"
        assert metadata["content_length"] == len("buyer question")
        assert metadata["content_hash"]
        assert metadata["reply_length"] > 0
        assert metadata["reply_hash"]

    asyncio.run(scenario())


def test_pipeline_internal_workflow_does_not_require_fastgpt_dataset_id():
    class FakeDb:
        def get_shop_by_platform_id(self, platform, shop_platform_id):
            return {
                "id": "db-shop-1",
                "shop_id": shop_platform_id,
                "shop_name": "shop",
                "fastgpt_dataset_id": "",
            }

    class FakeSessionManager:
        def __init__(self):
            self.messages = []
            self.statuses = {}

        async def get_or_create_conversation(self, shop_id, buyer_id, user_id):
            return SimpleNamespace(session_id="session-1", status="active")

        def add_message(self, session_id, role, content):
            self.messages.append((session_id, role, content))

        def set_status(self, session_id, status):
            self.statuses[session_id] = status

        def reset_fallback_state(self, session_id):
            pass

        def build_context_messages(self, *args, **kwargs):
            return []

        async def check_and_compress(self, *args, **kwargs):
            return None

    class FakeKeywordHandler:
        def check(self, shop_id, text):
            return {"matched": False}

    async def scenario():
        session_mgr = FakeSessionManager()
        workflow = RecordingWorkflowEngine(reply="internal reply")
        pipeline = MessagePipeline(
            FakeDb(),
            session_mgr,
            FakeKeywordHandler(),
            FakePipelineFastGpt(),
            None,
            workflow_engine=workflow,
        )
        result = await pipeline.process(
            {
                "buyer_id": "buyer-1",
                "shop_platform_id": "shop-1",
                "content": "buyer question",
                "user_id": "user-1",
                "message_type": "text",
            }
        )

        assert result["action"] == "reply"
        assert result["text"] == "internal reply"
        assert workflow.contexts[0].dataset_id == ""
        assert session_mgr.statuses == {}

    asyncio.run(scenario())


def test_pipeline_inherits_product_context_across_messages_and_isolates_sessions():
    async def scenario():
        session_mgr = FakePipelineSessionManager()
        workflow = RecordingWorkflowEngine(reply="safe reply")
        pipeline = MessagePipeline(
            FakePipelineDb(),
            session_mgr,
            FakePipelineKeywordHandler(),
            FakePipelineFastGpt(),
            None,
            workflow_engine=workflow,
        )

        await pipeline.process(
            {
                "buyer_id": "buyer-1",
                "shop_platform_id": "shop-1",
                "content": "product card",
                "user_id": "user-1",
                "message_type": "64",
                "goods_id": "goods-1",
                "goods_name": "Mini Balm",
            }
        )
        await pipeline.process(
            {
                "buyer_id": "buyer-1",
                "shop_platform_id": "shop-1",
                "content": "这个多少钱",
                "user_id": "user-1",
                "message_type": "text",
            }
        )
        await pipeline.process(
            {
                "buyer_id": "buyer-2",
                "shop_platform_id": "shop-1",
                "content": "这个多少钱",
                "user_id": "user-1",
                "message_type": "text",
            }
        )

        assert workflow.contexts[1].goods_context["goods_id"] == "goods-1"
        assert workflow.contexts[1].metadata["product_context_inherited"] is True
        assert workflow.contexts[1].metadata["product_context_age_messages"] == 1
        assert workflow.contexts[1].history
        assert workflow.contexts[2].goods_context in ({}, None)

    asyncio.run(scenario())


def test_workflow_history_extracts_product_anchor_from_text_card():
    session_mgr = FakePipelineSessionManager()
    session_id = "db-shop-1:buyer-1:user-1"
    session_mgr.add_message(session_id, "user", "商品：Mini Balm，价格：99，商品ID：mini-balm")
    pipeline = MessagePipeline(
        FakePipelineDb(),
        session_mgr,
        FakePipelineKeywordHandler(),
        FakePipelineFastGpt(),
        None,
        workflow_engine=RecordingWorkflowEngine(),
    )

    history = pipeline._workflow_history(session_id)

    assert history[0]["goods_id"] == "mini-balm"
    assert history[0]["goods_name"] == "Mini Balm"
    assert history[0]["history_has_product_card"] is True


def test_internal_safe_reply_with_human_phrase_triggers_transfer():
    async def scenario():
        session_mgr = FakePipelineSessionManager()
        workflow = RecordingWorkflowEngine(reply="Safe reply can ask human service to verify.")
        pipeline = MessagePipeline(
            FakePipelineDb(),
            session_mgr,
            FakePipelineKeywordHandler(),
            FakePipelineFastGpt(transfer_on_text=True),
            None,
            workflow_engine=workflow,
        )

        result = await pipeline.process(
            {
                "buyer_id": "buyer-1",
                "shop_platform_id": "shop-1",
                "content": "where is package",
                "user_id": "user-1",
                "message_type": "text",
            }
        )

        assert result["action"] == "transfer_human"
        assert session_mgr.statuses == {"db-shop-1:buyer-1:user-1": "pending_human"}

    asyncio.run(scenario())


def test_fastgpt_reply_still_uses_legacy_transfer_scan():
    async def scenario():
        session_mgr = FakePipelineSessionManager()
        workflow = RecordingWorkflowEngine(
            reply="Safe reply can ask human service to verify.",
            trace={"guardrail_status": ""},
        )
        pipeline = MessagePipeline(
            FakePipelineDb(),
            session_mgr,
            FakePipelineKeywordHandler(),
            FakePipelineFastGpt(transfer_on_text=True),
            None,
            workflow_engine=workflow,
        )

        result = await pipeline.process(
            {
                "buyer_id": "buyer-1",
                "shop_platform_id": "shop-1",
                "content": "where is package",
                "user_id": "user-1",
                "message_type": "text",
            }
        )

        assert result["action"] == "transfer_human"
        assert session_mgr.statuses == {"db-shop-1:buyer-1:user-1": "pending_human"}

    asyncio.run(scenario())


def test_pipeline_reply_and_transfer_actions_still_return_reply_text():
    async def scenario(action):
        handler = AIReplyHandler()
        handler._pipeline = OutcomePipeline(action, text=f"{action}-reply")

        result = await handler._get_ai_reply(
            "你好",
            SimpleNamespace(content="你好", kwargs=SimpleNamespace()),
        )

        assert result == f"{action}-reply"

    asyncio.run(scenario("reply"))
    asyncio.run(scenario("transfer_human"))


def test_session_fallback_throttle_allows_first_then_near_expiry_second():
    session_mgr = SessionManager(FakeConfigDb())

    assert session_mgr.should_send_fallback("s1", now=1000) == "first"
    session_mgr.mark_fallback_sent("s1", "first", now=1000)

    assert session_mgr.should_send_fallback("s1", now=1100) == ""
    assert session_mgr.should_send_fallback("s1", now=1240) == "second"

    session_mgr.mark_fallback_sent("s1", "second", now=1240)
    assert session_mgr.should_send_fallback("s1", now=2000) == ""


def test_session_compress_uses_configured_model_endpoint_and_auth(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "summary"}}]}

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr(session_module, "SESSION_COMPRESS_MODEL", "doubao-seed-2-0-mini-260215")
    monkeypatch.setattr(session_module, "SESSION_COMPRESS_BASE_URL", "http://host.docker.internal:11435")
    monkeypatch.setattr(session_module, "SESSION_COMPRESS_API_KEY", "test-key")
    monkeypatch.setattr(session_module, "SESSION_COMPRESS_MAX_TOKENS", 80)
    monkeypatch.setattr(session_module, "SESSION_COMPRESS_TEMPERATURE", 0.3)
    monkeypatch.setattr(session_module, "SESSION_COMPRESS_TIMEOUT", 20)

    async def scenario():
        session_mgr = SessionManager(FakeConfigDb())
        return await session_mgr._summarize_messages(
            [
                SimpleNamespace(role="user", content="hello"),
                SimpleNamespace(role="assistant", content="hi"),
            ]
        )

    assert asyncio.run(scenario()) == "summary"
    assert calls[0][0] == "http://host.docker.internal:11435/v1/chat/completions"
    assert calls[0][1]["json"]["model"] == "doubao-seed-2-0-mini-260215"
    assert calls[0][1]["json"]["max_tokens"] == 80
    assert calls[0][1]["headers"] == {"Authorization": "Bearer test-key"}
    assert calls[0][1]["timeout"] == 20


def test_auto_reply_manager_suspends_after_final_reconnect_failure():
    manager = AutoReplyManager()
    account_key = "pinduoduo_1_user"

    manager._on_connection_failed(account_key, "连接失败，已达到最大重试次数: closed")

    assert account_key in manager._suspended_until
    assert manager.start_auto_reply(
        {"channel_name": "pinduoduo", "shop_id": "1", "username": "user"}
    ) is False


def test_auto_reply_manager_alerts_on_final_reconnect_failure():
    notifier = FakeNotificationService()
    manager = AutoReplyManager(notification_service=notifier)
    account_key = "pinduoduo_565617_10000000000"

    manager._on_connection_failed(account_key, "连接失败，已达到最大重试次数: closed")

    assert notifier.alerts == [
        {
            "shop_id": "565617",
            "user_id": "10000000000",
            "reason": "自动回复连接失败: 连接失败，已达到最大重试次数: closed",
            "alert_level": "high",
        }
    ]


def test_queue_manager_recreates_queue_for_new_event_loop():
    queue_name = "test_cross_loop_queue"
    queue_manager._queues.pop(queue_name, None)

    async def get_queue():
        return queue_manager.get_or_create_queue(queue_name)

    try:
        first_queue = asyncio.run(get_queue())
        second_queue = asyncio.run(get_queue())

        assert second_queue is not first_queue
    finally:
        queue_manager._queues.pop(queue_name, None)
