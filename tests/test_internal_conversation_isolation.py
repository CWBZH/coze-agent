import Session.session_manager  # Import order avoids existing core/logger circular import.
import sqlite3

from Message.workflow.conversation_context import (
    ConversationRecord,
    InMemoryConversationContextRepository,
    SQLiteConversationContextRepository,
    stable_hash,
)
from Message.workflow.internal_engine import InternalWorkflowEngine
from Message.workflow.types import WorkflowContext, WorkflowAction


def _record(shop_id, user_id, buyer_id, session_id, content):
    return ConversationRecord(
        shop_id=shop_id,
        user_id=user_id,
        buyer_id=buyer_id,
        session_id=session_id,
        role="buyer",
        message_type="text",
        content=content,
        created_at=f"2026-05-21T01:00:0{len(content) % 9}Z",
        source="synthetic",
    )


def test_shop_buyer_isolation():
    repo = InMemoryConversationContextRepository(
        [
            _record("shop-a", "user-a", "buyer-a", "session-a", "wanted"),
            _record("shop-a", "user-a", "buyer-b", "session-a", "wrong-buyer"),
            _record("shop-b", "user-a", "buyer-a", "session-a", "wrong-shop"),
        ]
    )

    context = repo.load_context(
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="buyer-a",
        session_id="session-a",
    )

    hashes = {message.content_hash for message in context.history_window}
    assert hashes == {stable_hash("wanted")}


def test_session_isolation():
    repo = InMemoryConversationContextRepository(
        [
            _record("shop-a", "user-a", "buyer-a", "session-a", "wanted"),
            _record("shop-a", "user-a", "buyer-a", "session-b", "wrong-session"),
        ]
    )

    context = repo.load_context(
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="buyer-a",
        session_id="session-a",
    )

    assert [message.content_hash for message in context.history_window] == [stable_hash("wanted")]


def test_user_id_isolation():
    repo = InMemoryConversationContextRepository(
        [
            _record("shop-a", "user-a", "buyer-a", "session-a", "wanted"),
            _record("shop-a", "user-b", "buyer-a", "session-a", "wrong-user"),
        ]
    )

    context = repo.load_context(
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="buyer-a",
        session_id="session-a",
    )

    assert [message.content_hash for message in context.history_window] == [stable_hash("wanted")]


def test_history_window_does_not_include_full_content():
    full_content = "private full buyer message must not appear"
    repo = InMemoryConversationContextRepository(
        [_record("shop-a", "user-a", "buyer-a", "session-a", full_content)]
    )

    context = repo.load_context(
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="buyer-a",
        session_id="session-a",
    )

    message = context.history_window[0]
    assert message.content_hash == stable_hash(full_content)
    assert full_content not in message.content_summary
    assert "hash=" in message.content_summary


def test_internal_engine_uses_only_matching_conversation_history():
    repo = InMemoryConversationContextRepository(
        [
            _record("shop-a", "user-a", "buyer-a", "session-a", "wanted"),
            _record("shop-a", "user-a", "buyer-b", "session-a", "wrong-buyer"),
            _record("shop-b", "user-a", "buyer-a", "session-a", "wrong-shop"),
            _record("shop-a", "user-b", "buyer-a", "session-a", "wrong-user"),
            _record("shop-a", "user-a", "buyer-a", "session-b", "wrong-session"),
        ]
    )
    engine = InternalWorkflowEngine(conversation_context_repository=repo)
    context = WorkflowContext(
        trace_id="trace-history-isolation",
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="buyer-a",
        customer_uid="buyer-a",
        session_id="session-a",
        content="hello",
    )

    import asyncio

    result = asyncio.run(engine.run(context))

    assert result.trace["history_message_count"] == 1
    assert result.trace["history_window_size"] == 1
    assert context.history[0]["content_hash"] == stable_hash("wanted")
    assert "wrong-buyer" not in repr(context.history)
    assert "wrong-shop" not in repr(context.history)
    assert "wrong-user" not in repr(context.history)
    assert "wrong-session" not in repr(context.history)


def test_internal_engine_pending_human_lock_uses_matching_history_only():
    repo = InMemoryConversationContextRepository(
        [
            ConversationRecord(
                shop_id="shop-a",
                user_id="user-a",
                buyer_id="buyer-a",
                session_id="session-a",
                role="buyer",
                message_type="text",
                content="wanted pending human",
                created_at="2026-05-21T01:00:00Z",
                pending_human=True,
            ),
            ConversationRecord(
                shop_id="shop-a",
                user_id="user-a",
                buyer_id="buyer-b",
                session_id="session-a",
                role="buyer",
                message_type="text",
                content="wrong buyer pending human",
                created_at="2026-05-21T01:00:01Z",
                pending_human=True,
            ),
        ]
    )
    engine = InternalWorkflowEngine(conversation_context_repository=repo)
    context = WorkflowContext(
        trace_id="trace-pending-human",
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="buyer-a",
        customer_uid="buyer-a",
        session_id="session-a",
        content="hello",
    )

    import asyncio

    result = asyncio.run(engine.run(context))

    assert result.action == WorkflowAction.TRANSFER_HUMAN
    assert result.intent == "pending_human_lock"
    assert result.reason == "pending_human_conversation"
    assert result.trace["pending_human"] is True
    assert result.trace["history_message_count"] == 1
    assert context.history[0]["content_hash"] == stable_hash("wanted pending human")


def test_internal_engine_sqlite_pending_human_lock_does_not_call_repository(tmp_path):
    class ProductRepositorySpy:
        def __init__(self):
            self.calls = []

        def load_records(self, *, shop_id):
            self.calls.append(shop_id)
            return []

    db_path = tmp_path / "conversation.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE conversations (id TEXT PRIMARY KEY, shop_id TEXT, user_id TEXT, buyer_id TEXT, session_id TEXT, status TEXT)"
    )
    conn.execute(
        "CREATE TABLE messages (conversation_id TEXT, role TEXT, message_type TEXT, content TEXT, created_at TEXT, source TEXT)"
    )
    conn.execute(
        "INSERT INTO conversations (id, shop_id, user_id, buyer_id, session_id, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("conv-a", "shop-a", "user-a", "buyer-a", "session-a", "pending_human"),
    )
    conn.execute(
        "INSERT INTO messages (conversation_id, role, message_type, content, created_at, source) VALUES (?, ?, ?, ?, ?, ?)",
        ("conv-a", "buyer", "text", "sqlite pending content", "2026-05-21T01:00:00Z", "sqlite_test"),
    )
    conn.commit()
    conn.close()

    product_repository = ProductRepositorySpy()
    engine = InternalWorkflowEngine(
        knowledge_repository=product_repository,
        conversation_context_repository=SQLiteConversationContextRepository(db_path),
    )
    context = WorkflowContext(
        trace_id="trace-sqlite-pending-human",
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="buyer-a",
        customer_uid="buyer-a",
        session_id="session-a",
        content="Mini Balm price",
    )

    import asyncio

    result = asyncio.run(engine.run(context))

    assert result.action == WorkflowAction.TRANSFER_HUMAN
    assert result.intent == "pending_human_lock"
    assert product_repository.calls == []
    assert result.trace["history_source"] == "sqlite"
    assert result.trace["history_message_count"] == 1
    assert "sqlite pending content" not in repr(context.history)
