import json
import time
import asyncio
from pathlib import Path

from runtime.account_loader import load_candidate_accounts
from runtime.worker import _run_accounts
from web_api.services.shop_onboarding_service import ShopOnboardingService


class FakeDbManager:
    def __init__(self, enabled_shops: set[str]):
        self.enabled_shops = enabled_shops

    def get_all_accounts_with_details(self):
        return [
            {
                "channel_name": "pinduoduo",
                "shop_id": "shop-enabled",
                "user_id": "user-1",
                "username": "enabled-account",
                "status": 1,
            },
            {
                "channel_name": "pinduoduo",
                "shop_id": "shop-disabled",
                "user_id": "user-2",
                "username": "disabled-account",
                "status": 1,
            },
            {
                "channel_name": "pinduoduo",
                "shop_id": "shop-offline",
                "user_id": "user-3",
                "username": "offline-account",
                "status": 0,
            },
        ]

    def is_shop_ai_enabled(self, shop_id: str) -> bool:
        return shop_id in self.enabled_shops


def test_worker_candidate_accounts_require_shop_ai_enabled():
    accounts = load_candidate_accounts(FakeDbManager({"shop-enabled"}))

    assert [account["shop_id"] for account in accounts] == ["shop-enabled"]
    assert accounts[0]["user_id"] == "user-1"


def test_worker_candidate_accounts_do_not_fallback_to_enabled_without_setting():
    accounts = load_candidate_accounts(FakeDbManager(set()))

    assert accounts == []


def test_web_worker_status_reads_status_file_for_shop(tmp_path):
    status_file = tmp_path / "worker_status.json"
    status_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "worker_id": "worker-1",
                "pid": 123,
                "app_env": "test",
                "snapshot_phase": "running",
                "worker_state": "running",
                "started_at": time.time() - 30,
                "updated_at": time.time(),
                "connected_count": 1,
                "connections": [
                    {
                        "shop_id": "565617",
                        "user_id": "seller-user",
                        "username": "seller",
                        "state": "connected",
                    }
                ],
                "accounts": [
                    {
                        "account_key": "565617_seller-user",
                        "channel_name": "pinduoduo",
                        "shop_id": "565617",
                        "user_id": "seller-user",
                        "username": "seller",
                        "state": "running",
                    }
                ],
                "running_accounts": ["565617_seller-user"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    service = ShopOnboardingService(db_path=tmp_path / "web.db", worker_status_path=status_file)

    status = service.get_worker_status("565617")

    assert status["status"] == "running"
    assert status["websocket_status"] == "connected"
    assert status["process_id"] == 123
    assert status["last_seen_at"] is not None
    assert "seller-user" in status["summary"]
    assert status["ai_enabled"] is False
    assert status["consistency_status"] == "ai_disabled_worker_still_running"
    assert status["attention_required"] is True


def test_web_worker_status_is_stopped_for_shop_without_running_account(tmp_path):
    status_file = tmp_path / "worker_status.json"
    status_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "worker_id": "worker-1",
                "pid": 123,
                "worker_state": "running",
                "updated_at": time.time(),
                "accounts": [
                    {
                        "account_key": "other-user",
                        "shop_id": "other-shop",
                        "user_id": "other-user",
                        "state": "running",
                    }
                ],
                "running_accounts": ["other-user"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    service = ShopOnboardingService(db_path=tmp_path / "web.db", worker_status_path=status_file)

    status = service.get_worker_status("565617")

    assert status["status"] == "stopped"
    assert status["websocket_status"] == "unknown"
    assert status["ai_enabled"] is False
    assert status["consistency_status"] == "ai_disabled_worker_stopped"
    assert status["attention_required"] is False


def test_web_worker_status_warns_when_ai_enabled_but_worker_not_running(tmp_path):
    status_file = tmp_path / "worker_status.json"
    status_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "worker_id": "worker-1",
                "pid": 123,
                "worker_state": "running",
                "updated_at": time.time(),
                "accounts": [],
                "running_accounts": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    service = ShopOnboardingService(db_path=tmp_path / "web.db", worker_status_path=status_file)
    service.enable_ai("565617", confirm=True, override=True, override_reason="test_enable")

    status = service.get_worker_status("565617")

    assert status["status"] == "stopped"
    assert status["ai_enabled"] is True
    assert status["consistency_status"] == "ai_enabled_worker_not_running"
    assert status["attention_required"] is True
    assert status["recommended_action"]


def test_web_worker_status_marks_stale_file_as_attention_required(tmp_path):
    status_file = tmp_path / "worker_status.json"
    status_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "worker_id": "worker-1",
                "pid": 123,
                "worker_state": "running",
                "updated_at": time.time() - 120,
                "accounts": [
                    {
                        "account_key": "565617_seller-user",
                        "shop_id": "565617",
                        "user_id": "seller-user",
                        "state": "running",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    service = ShopOnboardingService(db_path=tmp_path / "web.db", worker_status_path=status_file)

    status = service.get_worker_status("565617")

    assert status["status"] == "stale"
    assert status["consistency_status"] == "worker_status_stale"
    assert status["attention_required"] is True


class ToggleDbManager:
    def __init__(self):
        self.enabled = True

    def is_shop_ai_enabled(self, shop_id: str) -> bool:
        return self.enabled


class StoppableChannel:
    instances = []

    def __init__(self):
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self.start_calls = []
        self.stop_calls = 0
        StoppableChannel.instances.append(self)

    async def start_account(self, shop_id, user_id, on_success=None, on_failure=None):
        self.start_calls.append((shop_id, user_id))
        if on_success:
            on_success()
        self.started.set()

    async def stop_all_connections(self):
        self.stop_calls += 1
        self.stopped.set()


def test_running_worker_stops_account_when_shop_ai_is_disabled(tmp_path):
    db_manager = ToggleDbManager()
    account = {
        "channel_name": "pinduoduo",
        "shop_id": "565617",
        "user_id": "seller-user",
        "username": "seller",
        "status": 1,
    }
    stop_event = asyncio.Event()
    StoppableChannel.instances = []

    async def scenario():
        task = asyncio.create_task(
            _run_accounts(
                [account],
                stop_event,
                status_file_path=tmp_path / "worker_status.json",
                status_interval=0,
                ai_gate_db_manager=db_manager,
                ai_gate_interval=0.01,
                channel_factory=StoppableChannel,
            )
        )
        for _ in range(50):
            if StoppableChannel.instances:
                break
            await asyncio.sleep(0.01)
        channel = StoppableChannel.instances[0]
        await asyncio.wait_for(channel.started.wait(), timeout=1)

        db_manager.enabled = False

        await asyncio.wait_for(channel.stopped.wait(), timeout=1)
        await asyncio.wait_for(task, timeout=1)
        assert channel.stop_calls == 1

    asyncio.run(scenario())
