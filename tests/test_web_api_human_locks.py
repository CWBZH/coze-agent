import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from web_api.deps import get_human_lock_service
from web_api.main import app
from web_api.services.human_lock_service import HumanLockService


def _client_for_db(db_path: Path) -> TestClient:
    app.dependency_overrides[get_human_lock_service] = lambda: HumanLockService(db_path)
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def _create_human_lock_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE shops (
                id INTEGER PRIMARY KEY,
                shop_id TEXT NOT NULL,
                shop_name TEXT NOT NULL
            );
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                shop_id INTEGER NOT NULL,
                buyer_id TEXT NOT NULL,
                user_id TEXT,
                status TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE agent_messages (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                timestamp TEXT NOT NULL
            );
            """
        )
        conn.execute("INSERT INTO shops (id, shop_id, shop_name) VALUES (1, '565617', 'shop-a')")
        conn.execute("INSERT INTO shops (id, shop_id, shop_name) VALUES (2, '323473738', 'shop-b')")
        conversations = [
            (1, "session-a", 1, "buyer-a", "pending_human", "2026-05-26 10:00:00", "2026-05-26 10:01:00"),
            (2, "session-b", 2, "buyer-b", "pending_human", "2026-05-26 10:02:00", "2026-05-26 10:03:00"),
            (3, "session-c", 1, "buyer-c", "active", "2026-05-26 10:04:00", "2026-05-26 10:05:00"),
            (4, "session-d", 1, "buyer-d", "pending_human", "2026-05-26 10:06:00", "2026-05-26 10:07:00"),
        ]
        conn.executemany(
            """
            INSERT INTO conversations
            (id, session_id, shop_id, buyer_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            conversations,
        )
        long_message = "这是一条很长的买家消息，用来验证 last_message_preview 会被截断。" * 8
        conn.execute(
            "INSERT INTO agent_messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            ("session-a", "buyer", long_message, "2026-05-26 10:01:30"),
        )
        conn.execute(
            "INSERT INTO agent_messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            ("session-b", "buyer", "另一家店铺的消息", "2026-05-26 10:03:30"),
        )
        conn.commit()
    finally:
        conn.close()


def _conversation_status(db_path: Path, conversation_id: int) -> str:
    conn = sqlite3.connect(db_path)
    try:
        return str(conn.execute("SELECT status FROM conversations WHERE id=?", (conversation_id,)).fetchone()[0])
    finally:
        conn.close()


def test_list_human_locks_requires_shop_id(tmp_path):
    db_path = tmp_path / "locks.db"
    _create_human_lock_db(db_path)
    client = _client_for_db(db_path)
    try:
        response = client.get("/api/human-locks")
        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "shop_id_required"
    finally:
        _clear_overrides()


def test_list_human_locks_is_shop_isolated_and_preview_is_truncated(tmp_path):
    db_path = tmp_path / "locks.db"
    _create_human_lock_db(db_path)
    client = _client_for_db(db_path)
    try:
        response = client.get("/api/human-locks?shop_id=565617")
        assert response.status_code == 200
        payload = response.json()
        assert payload["shop_id"] == "565617"
        assert payload["total"] == 2
        assert {item["buyer_id"] for item in payload["items"]} == {"buyer-a", "buyer-d"}
        assert all(item["shop_id"] == "565617" for item in payload["items"])
        preview = next(item["last_message_preview"] for item in payload["items"] if item["buyer_id"] == "buyer-a")
        assert len(preview) <= 120
        assert "buyer-b" not in response.text
    finally:
        _clear_overrides()


def test_single_unlock_requires_matching_shop_and_is_idempotent(tmp_path):
    db_path = tmp_path / "locks.db"
    _create_human_lock_db(db_path)
    client = _client_for_db(db_path)
    try:
        wrong_shop = client.post(
            "/api/human-locks/1/unlock",
            json={"shop_id": "323473738", "operator": "local_admin", "reason": "wrong_shop_attempt"},
        )
        assert wrong_shop.status_code == 404
        assert _conversation_status(db_path, 1) == "pending_human"

        unlocked = client.post(
            "/api/human-locks/1/unlock",
            json={"shop_id": "565617", "operator": "local_admin", "reason": "manual_unlock_after_review"},
        )
        assert unlocked.status_code == 200
        payload = unlocked.json()
        assert payload["unlocked"] is True
        assert payload["already_unlocked"] is False
        assert payload["shop_id"] == "565617"
        assert _conversation_status(db_path, 1) == "active"

        repeated = client.post(
            "/api/human-locks/1/unlock",
            json={"shop_id": "565617", "operator": "local_admin", "reason": "manual_unlock_after_review"},
        )
        assert repeated.status_code == 200
        assert repeated.json()["unlocked"] is False
        assert repeated.json()["already_unlocked"] is True
    finally:
        _clear_overrides()


def test_unlock_by_session_only_affects_target_shop(tmp_path):
    db_path = tmp_path / "locks.db"
    _create_human_lock_db(db_path)
    client = _client_for_db(db_path)
    try:
        response = client.post(
            "/api/human-locks/unlock-by-session",
            json={
                "shop_id": "565617",
                "buyer_id": "buyer-a",
                "session_id": "session-a",
                "operator": "local_admin",
                "reason": "manual_unlock_after_review",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["matched_count"] == 1
        assert payload["unlocked_count"] == 1
        assert _conversation_status(db_path, 1) == "active"
        assert _conversation_status(db_path, 2) == "pending_human"
    finally:
        _clear_overrides()


def test_unlock_by_session_requires_buyer_or_session(tmp_path):
    db_path = tmp_path / "locks.db"
    _create_human_lock_db(db_path)
    client = _client_for_db(db_path)
    try:
        response = client.post(
            "/api/human-locks/unlock-by-session",
            json={"shop_id": "565617", "operator": "local_admin", "reason": "missing_selector"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "buyer_id_or_session_id_required"
    finally:
        _clear_overrides()


def test_bulk_unlock_requires_shop_id_and_only_unlocks_current_shop(tmp_path):
    db_path = tmp_path / "locks.db"
    _create_human_lock_db(db_path)
    client = _client_for_db(db_path)
    try:
        missing_shop = client.post(
            "/api/human-locks/bulk-unlock",
            json={"operator": "local_admin", "reason": "bulk_unlock_after_deploy"},
        )
        assert missing_shop.status_code == 400

        response = client.post(
            "/api/human-locks/bulk-unlock",
            json={"shop_id": "565617", "operator": "local_admin", "reason": "bulk_unlock_after_deploy", "limit": 100},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["shop_id"] == "565617"
        assert payload["matched_count"] == 2
        assert payload["unlocked_count"] == 2
        assert _conversation_status(db_path, 1) == "active"
        assert _conversation_status(db_path, 4) == "active"
        assert _conversation_status(db_path, 2) == "pending_human"
    finally:
        _clear_overrides()


def test_human_lock_responses_do_not_expose_secrets(tmp_path):
    db_path = tmp_path / "locks.db"
    _create_human_lock_db(db_path)
    client = _client_for_db(db_path)
    try:
        response = client.get("/api/human-locks?shop_id=565617")
        text = response.text.lower()
        for forbidden in ("cookie", "password", "token", "authorization", "api_key", "postgresql://"):
            assert forbidden not in text
    finally:
        _clear_overrides()
