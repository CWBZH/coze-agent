from datetime import datetime

from core.human_alert_context import HumanAlertContext, format_human_alert_message
from core.pushplus_notifier import PushPlusNotifier


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

    assert "佳琪如梦（565617）" in message
    assert "13570354888" in message
    assert "6694171636407" in message
    assert "AI 判断需要转人工" in message
    assert "这个用了过敏怎么办" in message
    assert "pending_human" in message
    assert "2026-05-18 12:45:00" in message
