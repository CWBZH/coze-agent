import asyncio
import time
from types import SimpleNamespace

import Session.session_manager as session_module
from Message.core.pipeline import MessagePipeline
from Message.core.queue import queue_manager
from Message.handlers.ai_handler import AIReplyHandler
from Session.session_manager import SessionManager
from ui.auto_reply.manager import AutoReplyManager


class FakeNotificationService:
    def __init__(self):
        self.alerts = []

    def alert_human_fallback(self, shop_id, user_id, reason, alert_level="low"):
        self.alerts.append(
            {
                "shop_id": shop_id,
                "user_id": user_id,
                "reason": reason,
                "alert_level": alert_level,
            }
        )


class BlockingFastGPT:
    def call(self, *args, **kwargs):
        time.sleep(0.2)
        return {"success": True, "content": "ok", "tokens": 1}


class SkipPipeline:
    async def process(self, message):
        return {"action": "skip", "session_id": "s1", "status": "pending_human"}


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

        result = await handler._get_ai_reply("退款", SimpleNamespace(kwargs=SimpleNamespace()))

        assert result == handler.PIPELINE_SKIP

    asyncio.run(scenario())


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
    account_key = "pinduoduo_565617_13570354888"

    manager._on_connection_failed(account_key, "连接失败，已达到最大重试次数: closed")

    assert notifier.alerts == [
        {
            "shop_id": "565617",
            "user_id": "13570354888",
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
