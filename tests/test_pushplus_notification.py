from datetime import datetime

from core.human_alert_context import HumanAlertContext, format_human_alert_message
from core.notification import HeadlessNotificationService, NotificationService
from core.pushplus_notifier import PushPlusNotifier


class FakePushPlusNotifier:
    def __init__(self, should_raise=False):
        self.should_raise = should_raise
        self.calls = []

    def send(self, title, content):
        if self.should_raise:
            raise RuntimeError("pushplus down")
        self.calls.append({"title": title, "content": content})
        return type("Result", (), {"sent": True, "skipped": False, "reason": ""})()


class FakeAlertContextBuilder:
    def __init__(self, user_message=None, assistant_message=None):
        self.user_message = user_message or ""
        self.assistant_message = assistant_message or ""

    def build(self, shop_id, buyer_id):
        return HumanAlertContext(
            shop_id=str(shop_id),
            shop_name="shop",
            account_name="account",
            buyer_id=str(buyer_id),
            session_id="session-1",
            session_status="pending_human",
            latest_user_message=self.user_message,
            latest_assistant_message=self.assistant_message,
        )


def test_pushplus_disabled_without_token_is_skipped():
    notifier = PushPlusNotifier(enabled=True, token="")

    result = notifier.send("title", "content")

    assert result.sent is False
    assert result.skipped is True
    assert result.reason == "missing_token"


def test_human_alert_message_contains_actionable_context():
    context = HumanAlertContext(
        shop_id="565617",
        shop_name="佳琪如梦",
        account_name="13570354888",
        buyer_id="6694171636407",
        session_id="s1",
        session_status="pending_human",
        latest_user_message="这个用了过敏怎么办",
        latest_assistant_message="已为你转接人工客服请稍等~",
    )

    message = format_human_alert_message(
        context,
        reason="AI 判断需要转人工",
        alert_level="high",
        now=datetime(2026, 5, 18, 12, 45, 0),
    )

    assert "shop=佳琪如梦 (565617)" in message
    assert "13570354888" in message
    assert "6694171636407" in message
    assert "reason=AI 判断需要转人工" in message
    assert "这个用了过敏怎么办" in message
    assert "pending_human" in message
    assert "timestamp=2026-05-18 12:45:00" in message


def test_headless_notification_service_sends_controlled_redacted_preview():
    buyer_secret = "buyer-secret"
    bearer_secret = "abc123"
    ark_secret = "ark-" + "secret"
    fastgpt_secret = "fastgpt-" + "secret"
    seller_secret = "seller-secret"
    hidden_secret = "hidden"
    user_message = (
        "token=" + buyer_secret + " Bearer " + bearer_secret + " "
        + ark_secret + " " + fastgpt_secret + " " + "A" * 700
    )
    assistant_message = (
        "cookie=" + seller_secret + " access_token=" + hidden_secret
        + " api_key=" + hidden_secret + " secret=" + hidden_secret + " "
        + "B" * 700
    )
    notifier = FakePushPlusNotifier()
    service = HeadlessNotificationService(
        pushplus_notifier=notifier,
        context_builder=FakeAlertContextBuilder(user_message, assistant_message),
    )

    service.alert_human_fallback(
        shop_id="shop-1",
        user_id="buyer-1",
        reason="send failed",
        alert_level="high",
        metadata={
            "trace_id": "trace-1",
            "source_message_id": "source-1",
            "queue_message_id": "queue-1",
            "session_id": "session-1",
            "message_type": "text",
            "content_length": 712,
            "content_hash": "contenthash",
            "reply_length": 713,
            "reply_hash": "replyhash",
            "final_status": "reply_send_failed",
            "action": "send_failed",
        },
    )

    assert len(notifier.calls) == 1
    content = notifier.calls[0]["content"]
    assert "trace_id=trace-1" in content
    assert "source_message_id=source-1" in content
    assert "queue_message_id=queue-1" in content
    assert "content_length=712" in content
    assert "content_hash=contenthash" in content
    assert "reply_length=713" in content
    assert "reply_hash=replyhash" in content
    assert "final_status=reply_send_failed" in content
    assert "buyer_message_truncated=true" in content
    assert "seller_or_ai_reply_truncated=true" in content
    assert "A" * 501 not in content
    assert "B" * 501 not in content
    assert buyer_secret not in content
    assert seller_secret not in content
    assert bearer_secret not in content
    assert ark_secret not in content
    assert fastgpt_secret not in content
    assert "***REDACTED***" in content


def test_headless_notification_service_isolates_pushplus_failure():
    service = HeadlessNotificationService(
        pushplus_notifier=FakePushPlusNotifier(should_raise=True),
        context_builder=FakeAlertContextBuilder("buyer", "assistant"),
    )

    service.alert_human_fallback(
        shop_id="shop-1",
        user_id="buyer-1",
        reason="send failed",
        alert_level="high",
        metadata={"trace_id": "trace-1"},
    )


def test_configure_standard_services_uses_headless_pushplus_when_enabled(monkeypatch):
    import core.config as config
    import core.di_container as di

    monkeypatch.setenv("HEADLESS_MODE", "1")
    monkeypatch.setattr(config, "PUSHPLUS_ENABLED", True)
    monkeypatch.setattr(config, "PUSHPLUS_TOKEN", "fake-token")
    di.container._services.clear()
    di.container._singletons.clear()
    di.container._scoped_instances.clear()

    try:
        configured = di.configure_standard_services()
        service = configured.get(NotificationService)

        assert isinstance(service, HeadlessNotificationService)
    finally:
        di.container._services.clear()
        di.container._singletons.clear()
        di.container._scoped_instances.clear()


def test_configure_standard_services_uses_pushplus_without_headless_mode(monkeypatch):
    import core.config as config
    import core.di_container as di

    monkeypatch.delenv("HEADLESS_MODE", raising=False)
    monkeypatch.setattr(config, "PUSHPLUS_ENABLED", True)
    monkeypatch.setattr(config, "PUSHPLUS_TOKEN", "fake-token")
    di.container._services.clear()
    di.container._singletons.clear()
    di.container._scoped_instances.clear()

    try:
        configured = di.configure_standard_services()
        service = configured.get(NotificationService)

        assert isinstance(service, HeadlessNotificationService)
    finally:
        di.container._services.clear()
        di.container._singletons.clear()
        di.container._scoped_instances.clear()


def test_configure_standard_services_uses_dummy_when_headless_pushplus_missing(monkeypatch):
    import core.config as config
    import core.di_container as di
    from core.notification import DummyNotificationService

    monkeypatch.setenv("HEADLESS_MODE", "1")
    monkeypatch.setattr(config, "PUSHPLUS_ENABLED", True)
    monkeypatch.setattr(config, "PUSHPLUS_TOKEN", "")
    di.container._services.clear()
    di.container._singletons.clear()
    di.container._scoped_instances.clear()

    try:
        configured = di.configure_standard_services()
        service = configured.get(NotificationService)

        assert isinstance(service, DummyNotificationService)
    finally:
        di.container._services.clear()
        di.container._singletons.clear()
        di.container._scoped_instances.clear()


def test_configure_standard_services_uses_dummy_without_pushplus_and_without_ui(monkeypatch):
    import core.config as config
    import core.di_container as di
    from core.notification import DummyNotificationService

    monkeypatch.delenv("HEADLESS_MODE", raising=False)
    monkeypatch.setattr(config, "PUSHPLUS_ENABLED", False)
    monkeypatch.setattr(config, "PUSHPLUS_TOKEN", "")
    di.container._services.clear()
    di.container._singletons.clear()
    di.container._scoped_instances.clear()

    try:
        configured = di.configure_standard_services()
        service = configured.get(NotificationService)

        assert isinstance(service, DummyNotificationService)
    finally:
        di.container._services.clear()
        di.container._singletons.clear()
        di.container._scoped_instances.clear()
