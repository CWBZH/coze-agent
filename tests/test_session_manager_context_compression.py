import asyncio
from types import SimpleNamespace

import Session.session_manager as session_module
from Session.session_manager import SessionManager


def test_session_compression_keeps_20_messages_and_summarizes_first_10():
    manager = SessionManager.__new__(SessionManager)
    messages = [
        SimpleNamespace(role="user", content=f"history {index}")
        for index in range(25)
    ]
    captured = {}

    manager.count_messages = lambda session_id: 25
    manager.get_recent_messages = lambda session_id, limit=40: captured.setdefault("limit", limit) and messages

    async def summarize(old_messages):
        captured["old_messages"] = list(old_messages)
        return "较早对话摘要"

    manager._summarize_messages = summarize
    manager._replace_with_summary = lambda session_id, old_messages, summary: captured.update(
        {
            "replaced": list(old_messages),
            "summary": summary,
        }
    )

    asyncio.run(manager.check_and_compress("session-1"))

    assert session_module.CONTEXT_FULL_MESSAGE_LIMIT == 20
    assert session_module.CONTEXT_COMPRESS_OLD_COUNT == 10
    assert captured["limit"] >= 30
    assert len(captured["old_messages"]) == 10
    assert captured["old_messages"][0].content == "history 0"
    assert captured["old_messages"][-1].content == "history 9"
    assert captured["replaced"] == captured["old_messages"]
    assert captured["summary"] == "较早对话摘要"


def test_session_compression_skips_when_history_is_within_20_messages():
    manager = SessionManager.__new__(SessionManager)
    captured = {}
    manager.count_messages = lambda session_id: 20
    manager.get_recent_messages = lambda *args, **kwargs: captured.update({"loaded": True}) or []

    asyncio.run(manager.check_and_compress("session-1"))

    assert captured == {}
