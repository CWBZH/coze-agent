from datetime import datetime


class FakeNotificationService:
    def __init__(self):
        self.alerts = []

    def alert_human_fallback(self, **kwargs):
        self.alerts.append(kwargs)


def test_pdd_worker_connection_failure_alerts_once_per_throttle_window():
    from core.worker_alerts import alert_pdd_worker_connection_failure

    notifier = FakeNotificationService()
    first = alert_pdd_worker_connection_failure(
        shop_id="565617",
        user_id="713439",
        error_msg="连接失败，已达到最大重试次数: no close frame received or sent",
        notification_service=notifier,
        now=datetime(2026, 5, 27, 13, 14, 7),
    )
    second = alert_pdd_worker_connection_failure(
        shop_id="565617",
        user_id="713439",
        error_msg="连接失败，已达到最大重试次数: no close frame received or sent",
        notification_service=notifier,
        now=datetime(2026, 5, 27, 13, 15, 0),
    )
    third = alert_pdd_worker_connection_failure(
        shop_id="565617",
        user_id="713439",
        error_msg="连接失败，已达到最大重试次数: no close frame received or sent",
        notification_service=notifier,
        now=datetime(2026, 5, 27, 13, 25, 0),
    )

    assert first["alerted"] is True
    assert second["alerted"] is False
    assert second["reason"] == "throttled"
    assert third["alerted"] is True
    assert len(notifier.alerts) == 2
    assert notifier.alerts[0]["shop_id"] == "565617"
    assert notifier.alerts[0]["user_id"] == "713439"
    assert notifier.alerts[0]["alert_level"] == "high"
    assert "PDD worker websocket disconnected" in notifier.alerts[0]["reason"]
    assert notifier.alerts[0]["metadata"]["event"] == "pdd_worker_connection_failed"
    assert notifier.alerts[0]["metadata"]["sends_pdd"] is False
    assert notifier.alerts[0]["metadata"]["calls_llm"] is False


def test_pdd_worker_connection_failure_alert_failure_is_isolated():
    from core.worker_alerts import alert_pdd_worker_connection_failure

    class BrokenNotificationService:
        def alert_human_fallback(self, **kwargs):
            raise RuntimeError("pushplus down")

    result = alert_pdd_worker_connection_failure(
        shop_id="323473738",
        user_id="163349769",
        error_msg="连接失败，已达到最大重试次数: no close frame received or sent",
        notification_service=BrokenNotificationService(),
        now=datetime(2026, 5, 27, 13, 14, 7),
    )

    assert result["alerted"] is False
    assert result["reason"] == "notification_failed"
    assert result["error_type"] == "RuntimeError"


def test_pdd_worker_startup_test_alert_uses_pushplus_without_pdd_send():
    from core.worker_alerts import send_pdd_worker_startup_test_alert

    class FakePushPlusNotifier:
        def __init__(self):
            self.messages = []

        def send(self, title, content):
            self.messages.append((title, content))

            class Result:
                sent = True
                skipped = False
                reason = ""
                response_code = 200

            return Result()

    notifier = FakePushPlusNotifier()

    result = send_pdd_worker_startup_test_alert(
        "565617",
        "713439",
        pushplus_notifier=notifier,
    )

    assert result["alerted"] is True
    assert notifier.messages
    title, content = notifier.messages[0]
    assert title == "Worker startup test"
    assert "shop_id=565617" in content
    assert "No PDD message is sent." in content
