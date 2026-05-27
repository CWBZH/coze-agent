import Session.session_manager  # Import order avoids existing core/logger circular import.
import sqlite3

from Message.workflow.conversation_context import (
    ConversationRecord,
    InMemoryConversationContextRepository,
    SQLiteConversationContextRepository,
    stable_hash,
    summarize_content,
)


def _record(**overrides):
    base = {
        "shop_id": "shop-a",
        "user_id": "user-a",
        "buyer_id": "buyer-a",
        "session_id": "session-a",
        "role": "buyer",
        "message_type": "text",
        "content": "buyer full private message should not be stored as summary",
        "created_at": "2026-05-21T01:00:00Z",
        "source": "synthetic",
    }
    base.update(overrides)
    return ConversationRecord(**base)


def test_empty_history_returns_empty_context():
    repo = InMemoryConversationContextRepository()

    context = repo.load_context(
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="buyer-a",
        session_id="session-a",
    )

    assert context.history_message_count == 0
    assert context.history_window == ()
    assert context.pending_human is False


def test_history_window_is_sorted_and_limited_to_recent_messages():
    repo = InMemoryConversationContextRepository(
        [
            _record(content="one", created_at="2026-05-21T01:00:00Z"),
            _record(content="two", created_at="2026-05-21T01:01:00Z"),
            _record(content="three", created_at="2026-05-21T01:02:00Z"),
        ]
    )

    context = repo.load_context(
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="buyer-a",
        session_id="session-a",
        limit=2,
    )

    assert context.history_message_count == 3
    assert [message.content_hash for message in context.history_window] == [
        stable_hash("two"),
        stable_hash("three"),
    ]


def test_content_summary_uses_length_and_hash_not_full_original():
    content = "this is private buyer text"

    summary = summarize_content(content)

    assert summary == f"len={len(content)} hash={stable_hash(content)}"
    assert content not in summary


def test_pending_human_and_last_action_are_expressed():
    repo = InMemoryConversationContextRepository(
        [
            _record(
                content="first",
                created_at="2026-05-21T01:00:00Z",
                human_state="pending_human",
                pending_human=True,
                intent="after_sales_evidence_collection",
                action="request_evidence",
            )
        ]
    )

    context = repo.load_context(
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="buyer-a",
        session_id="session-a",
    )

    assert context.pending_human is True
    assert context.human_state == "pending_human"
    assert context.last_intent == "after_sales_evidence_collection"
    assert context.last_action == "request_evidence"


def test_content_hash_is_stable():
    assert stable_hash("same") == stable_hash("same")
    assert stable_hash("same") != stable_hash("other")


def _sqlite_db(tmp_path):
    db_path = tmp_path / "conversation.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            shop_id TEXT,
            user_id TEXT,
            buyer_id TEXT,
            session_id TEXT,
            human_state TEXT,
            pending_human INTEGER,
            status TEXT,
            last_intent TEXT,
            last_action TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT,
            role TEXT,
            message_type TEXT,
            content TEXT,
            created_at TEXT,
            source TEXT
        )
        """
    )
    return db_path, conn


def _insert_conversation(
    conn,
    *,
    conversation_id="conv-a",
    shop_id="shop-a",
    user_id="user-a",
    buyer_id="buyer-a",
    session_id="session-a",
    pending_human=0,
    human_state="",
    status="",
):
    conn.execute(
        """
        INSERT INTO conversations
            (id, shop_id, user_id, buyer_id, session_id, human_state, pending_human, status, last_intent, last_action)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            conversation_id,
            shop_id,
            user_id,
            buyer_id,
            session_id,
            human_state,
            pending_human,
            status,
            "product_basic",
            "reply",
        ),
    )


def _insert_message(conn, conversation_id, content, created_at):
    conn.execute(
        """
        INSERT INTO messages (conversation_id, role, message_type, content, created_at, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (conversation_id, "buyer", "text", content, created_at, "sqlite_test"),
    )


def test_sqlite_repository_loads_matching_history_only(tmp_path):
    db_path, conn = _sqlite_db(tmp_path)
    _insert_conversation(conn, conversation_id="conv-a")
    _insert_conversation(conn, conversation_id="conv-wrong-shop", shop_id="shop-b")
    _insert_conversation(conn, conversation_id="conv-wrong-buyer", buyer_id="buyer-b")
    _insert_conversation(conn, conversation_id="conv-wrong-session", session_id="session-b")
    _insert_message(conn, "conv-a", "wanted one", "2026-05-21T01:00:00Z")
    _insert_message(conn, "conv-a", "wanted two", "2026-05-21T01:01:00Z")
    _insert_message(conn, "conv-wrong-shop", "wrong shop", "2026-05-21T01:02:00Z")
    _insert_message(conn, "conv-wrong-buyer", "wrong buyer", "2026-05-21T01:03:00Z")
    _insert_message(conn, "conv-wrong-session", "wrong session", "2026-05-21T01:04:00Z")
    conn.commit()
    conn.close()

    repo = SQLiteConversationContextRepository(db_path)
    context = repo.load_context(
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="buyer-a",
        session_id="session-a",
    )

    assert context.history_source == "sqlite"
    assert context.history_message_count == 2
    assert [message.content_hash for message in context.history_window] == [
        stable_hash("wanted one"),
        stable_hash("wanted two"),
    ]
    rendered = repr(context.history_window)
    assert "wanted one" not in rendered
    assert "wrong shop" not in rendered
    assert "wrong buyer" not in rendered
    assert "wrong session" not in rendered


def test_sqlite_repository_user_id_isolation(tmp_path):
    db_path, conn = _sqlite_db(tmp_path)
    _insert_conversation(conn, conversation_id="conv-a")
    _insert_conversation(conn, conversation_id="conv-user-b", user_id="user-b")
    _insert_message(conn, "conv-a", "wanted user", "2026-05-21T01:00:00Z")
    _insert_message(conn, "conv-user-b", "wrong user", "2026-05-21T01:01:00Z")
    conn.commit()
    conn.close()

    context = SQLiteConversationContextRepository(db_path).load_context(
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="buyer-a",
        session_id="session-a",
    )

    assert context.history_message_count == 1
    assert context.history_window[0].content_hash == stable_hash("wanted user")


def test_sqlite_repository_limit_sorting_and_pending_human(tmp_path):
    db_path, conn = _sqlite_db(tmp_path)
    _insert_conversation(
        conn,
        conversation_id="conv-a",
        pending_human=1,
        human_state="pending_human",
        status="human",
    )
    _insert_message(conn, "conv-a", "old", "2026-05-21T01:00:00Z")
    _insert_message(conn, "conv-a", "new", "2026-05-21T01:01:00Z")
    conn.commit()
    conn.close()

    context = SQLiteConversationContextRepository(db_path).load_context(
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="buyer-a",
        session_id="session-a",
        limit=1,
    )

    assert context.pending_human is True
    assert context.human_state == "pending_human"
    assert context.history_message_count == 2
    assert [message.content_hash for message in context.history_window] == [stable_hash("new")]


def test_sqlite_repository_missing_db_or_table_returns_empty(tmp_path):
    missing = tmp_path / "missing.sqlite"
    missing_context = SQLiteConversationContextRepository(missing).load_context(
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="buyer-a",
        session_id="session-a",
    )
    assert missing_context.history_message_count == 0
    assert missing_context.history_source == "sqlite_missing"

    empty_db = tmp_path / "empty.sqlite"
    sqlite3.connect(empty_db).close()
    empty_context = SQLiteConversationContextRepository(empty_db).load_context(
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="buyer-a",
        session_id="session-a",
    )
    assert empty_context.history_message_count == 0
    assert empty_context.history_window == ()


def test_sqlite_repository_refuses_empty_identity_without_full_scan(tmp_path):
    db_path, conn = _sqlite_db(tmp_path)
    _insert_conversation(conn, conversation_id="conv-a")
    _insert_message(conn, "conv-a", "should not scan", "2026-05-21T01:00:00Z")
    conn.commit()
    conn.close()

    context = SQLiteConversationContextRepository(db_path).load_context(
        shop_id="shop-a",
        user_id="user-a",
        buyer_id="",
        session_id="session-a",
    )

    assert context.history_message_count == 0
