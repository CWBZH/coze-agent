from datetime import datetime

from database.db_manager import DatabaseManager
from database.models import AgentMessage, Conversation
from core.connection_status import ConnectionState, ConnectionStatus
from ui.dashboard_ui import build_dashboard_snapshot


class FakeAutoReplyManager:
    def __init__(self, running_keys=None):
        self.running_keys = set(running_keys or [])

    def is_running(self, account_data):
        key = f"{account_data['channel_name']}_{account_data['shop_id']}_{account_data['username']}"
        return key in self.running_keys


class FakeConnectionStatusManager:
    def __init__(self, statuses):
        self.statuses = statuses

    def get_all_status(self):
        return self.statuses


def test_dashboard_snapshot_contains_shop_account_runtime_and_counts(tmp_path):
    db = DatabaseManager(str(tmp_path / "dashboard.db"))
    db.add_shop("pinduoduo", "shop-1", "Shop One")
    db.add_account("pinduoduo", "shop-1", "u-1", "alice", "secret")
    db.update_account_status("pinduoduo", "shop-1", "u-1", 1)

    shop = db.get_shop("pinduoduo", "shop-1")
    with db.session_scope() as session:
        conv = Conversation(
            session_id="session-1",
            shop_id=shop["id"],
            buyer_id="buyer-1",
            user_id="u-1",
            status="pending_human",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session.add(conv)
        session.add(AgentMessage(session_id="session-1", role="user", content="hello"))
        session.add(AgentMessage(session_id="session-1", role="assistant", content="hi"))

    auto_reply = FakeAutoReplyManager({"pinduoduo_shop-1_alice"})
    status_manager = FakeConnectionStatusManager(
        [
            ConnectionStatus(
                shop_id="shop-1",
                user_id="u-1",
                username="alice",
                state=ConnectionState.CONNECTED,
            )
        ]
    )

    snapshot = build_dashboard_snapshot(db, auto_reply, status_manager)

    assert snapshot["stats"] == {
        "online": 1,
        "total": 1,
        "messages": 2,
        "transfers": 1,
        "avg_latency": 0,
    }
    assert snapshot["shops"] == [
        {
            "shop_id": "shop-1",
            "name": "Shop One",
            "account": "alice",
            "account_status": "在线",
            "auto_reply": True,
            "connection_state": "connected",
            "online": True,
            "msgs": 2,
            "transfers": 1,
            "conversations": 1,
            "last_error": "",
        }
    ]
