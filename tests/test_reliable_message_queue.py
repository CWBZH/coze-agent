import asyncio

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from bridge.context import ChannelType, Context, ContextType
from Message.core.outbox_worker import OutboxWorker, trigger_reconnect_recovery
from Message.core.reliable_queue import ReliableQueueStore
from Message.core.queue import SimpleMessageQueue
from Message.models.queue_models import QueueConfig


def _context(message: str = "buyer text", *, source_message_id: str = "msg-1") -> Context:
    return Context.create_pinduoduo_context(
        content=message,
        msg_id=source_message_id,
        from_uid="buyer-1",
        to_uid="seller-1",
        shop_id="shop-1",
        user_id="user-1",
        username="seller",
        user_msg_type=ContextType.TEXT,
        channel_type=ChannelType.PINDUODUO,
        trace_id=f"trace-{source_message_id}",
        source_message_id=source_message_id,
        queue_name="pdd_shop-1",
        message_type="text",
    )


def test_inbound_store_deduplicates_and_recovers_pending(tmp_path):
    store = ReliableQueueStore(tmp_path / "queue.db")
    first = store.enqueue_inbound(queue_name="pdd_shop-1", context=_context("one", source_message_id="msg-1"))
    duplicate = store.enqueue_inbound(queue_name="pdd_shop-1", context=_context("one", source_message_id="msg-1"))

    assert first.record_id == duplicate.record_id
    assert duplicate.created is False

    pending = store.recover_inbound(queue_name="pdd_shop-1", limit=10)
    assert len(pending) == 1
    assert pending[0].context.content == "one"
    assert pending[0].source_message_id == "msg-1"


def test_inbound_processing_timeout_is_recovered(tmp_path):
    store = ReliableQueueStore(tmp_path / "queue.db")
    record = store.enqueue_inbound(queue_name="pdd_shop-1", context=_context("timeout", source_message_id="msg-2"))
    store.mark_inbound_processing(record.record_id)

    recovered_none = store.recover_inbound(queue_name="pdd_shop-1", processing_timeout_seconds=3600)
    assert recovered_none == []

    recovered = store.recover_inbound(queue_name="pdd_shop-1", processing_timeout_seconds=0)
    assert [item.record_id for item in recovered] == [record.record_id]


def test_outbox_status_keeps_reply_send_failed_separate_from_transfer(tmp_path):
    store = ReliableQueueStore(tmp_path / "queue.db")
    reply = store.create_outbox(
        trace_id="trace-1",
        inbound_record_id="in-1",
        shop_id="shop-1",
        user_id="user-1",
        buyer_id="buyer-1",
        session_id="session-1",
        reply_action="reply",
        reply_text="safe reply",
        reply_source="internal",
    )
    transfer = store.create_outbox(
        trace_id="trace-2",
        inbound_record_id="in-2",
        shop_id="shop-1",
        user_id="user-1",
        buyer_id="buyer-1",
        session_id="session-2",
        reply_action="transfer_human",
        reply_text="transfer",
        reply_source="internal",
    )

    store.mark_outbox_failed(reply.outbox_id, pdd_error_code="40013")
    store.mark_outbox_failed(transfer.outbox_id, pdd_error_code="40013")

    assert store.get_outbox(reply.outbox_id)["status"] == "reply_send_failed"
    assert store.get_outbox(transfer.outbox_id)["status"] == "transfer_send_failed"


def test_simple_message_queue_rehydrates_persisted_pending(tmp_path):
    async def scenario():
        store = ReliableQueueStore(tmp_path / "queue.db")
        await SimpleMessageQueue("pdd_shop-1", QueueConfig(), reliable_store=store).put(_context("persisted"))

        recovered_queue = SimpleMessageQueue("pdd_shop-1", QueueConfig(), reliable_store=store)
        recovered = await recovered_queue.get(timeout=0.1)

        assert recovered is not None
        assert recovered.context.content == "persisted"
        assert recovered.reliable_record_id

    asyncio.run(scenario())


def test_outbox_worker_retries_due_reply_and_marks_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("PDD_SENDING_ENABLED", "true")

    async def scenario():
        store = ReliableQueueStore(tmp_path / "queue.db")
        outbox = store.create_outbox(
            trace_id="trace-1",
            inbound_record_id="in-1",
            shop_id="shop-1",
            user_id="user-1",
            buyer_id="buyer-1",
            session_id="session-1",
            reply_action="reply",
            reply_text="safe reply",
            reply_source="internal",
        )
        store.mark_outbox_failed(outbox.outbox_id, pdd_error_code="40013")

        sent = []

        class FakeSender:
            def __init__(self, shop_id, user_id):
                self.shop_id = shop_id
                self.user_id = user_id

            def send_text(self, buyer_id, reply_text):
                sent.append((self.shop_id, self.user_id, buyer_id, reply_text))
                return {"success": True, "result": {"result": "ok"}}

        worker = OutboxWorker(store=store, sender_factory=FakeSender)
        summary = await worker.run_due_retries(now=store._now() + 3600)

        assert summary["retried"] == 1
        assert sent == [("shop-1", "user-1", "buyer-1", "safe reply")]
        assert store.get_outbox(outbox.outbox_id)["status"] == "sent"

    asyncio.run(scenario())


def test_outbox_worker_suppresses_when_pdd_sending_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("PDD_SENDING_ENABLED", raising=False)

    async def scenario():
        store = ReliableQueueStore(tmp_path / "queue.db")
        outbox = store.create_outbox(
            trace_id="trace-disabled",
            inbound_record_id="in-disabled",
            shop_id="shop-1",
            user_id="user-1",
            buyer_id="buyer-1",
            session_id="session-1",
            reply_action="reply",
            reply_text="safe reply",
            reply_source="internal",
        )
        store.mark_outbox_failed(outbox.outbox_id, pdd_error_code="40013")

        class FailIfCalled:
            def __init__(self, shop_id, user_id):
                raise AssertionError("PDD sender must not be created while sending is disabled")

        worker = OutboxWorker(store=store, sender_factory=FailIfCalled)
        summary = await worker.run_due_retries(now=store._now() + 3600)

        assert summary["retried"] == 0
        assert summary["suppressed"] == 1
        assert store.get_outbox(outbox.outbox_id)["status"] == "pdd_sending_disabled"

    asyncio.run(scenario())


def test_outbox_claim_marks_rows_sending_before_retry(tmp_path):
    store = ReliableQueueStore(tmp_path / "queue.db")
    outbox = store.create_outbox(
        trace_id="trace-claim",
        inbound_record_id="in-claim",
        shop_id="shop-1",
        user_id="user-1",
        buyer_id="buyer-1",
        session_id="session-1",
        reply_action="reply",
        reply_text="safe reply",
        reply_source="internal",
    )
    store.mark_outbox_failed(outbox.outbox_id, pdd_error_code="40013")

    claimed = store.claim_retryable_outbox(now=store._now() + 3600)
    claimed_again = store.claim_retryable_outbox(now=store._now() + 3600)

    assert [row["id"] for row in claimed] == [outbox.outbox_id]
    assert claimed_again == []
    assert store.get_outbox(outbox.outbox_id)["status"] == "sending"


def test_outbox_recovers_stale_sending_records(tmp_path):
    store = ReliableQueueStore(tmp_path / "queue.db")
    outbox = store.create_outbox(
        trace_id="trace-stale",
        inbound_record_id="in-stale",
        shop_id="shop-1",
        user_id="user-1",
        buyer_id="buyer-1",
        session_id="session-1",
        reply_action="reply",
        reply_text="safe reply",
        reply_source="internal",
    )
    store.mark_outbox_sending(outbox.outbox_id)
    now = store._now()
    with store._connect() as conn:
        conn.execute(
            "UPDATE pdd_reply_outbox SET last_attempt_at = ?, updated_at = ? WHERE id = ?",
            (now - 120, now - 120, outbox.outbox_id),
        )

    recovered = store.recover_stale_sending_outbox(now=now, timeout_seconds=60)

    assert recovered == 1
    row = store.get_outbox(outbox.outbox_id)
    assert row["status"] == "reply_delivery_unknown"
    assert row["next_retry_at"] == now


def test_outbox_worker_suppresses_recent_duplicate_reply(tmp_path, monkeypatch):
    monkeypatch.setenv("PDD_SENDING_ENABLED", "true")

    async def scenario():
        store = ReliableQueueStore(tmp_path / "queue.db")
        sent = store.create_outbox(
            trace_id="trace-sent",
            inbound_record_id="in-sent",
            shop_id="shop-1",
            user_id="user-1",
            buyer_id="buyer-1",
            session_id="session-1",
            reply_action="reply",
            reply_text="same reply",
            reply_source="internal",
        )
        store.mark_outbox_sent(sent.outbox_id)
        failed = store.create_outbox(
            trace_id="trace-failed",
            inbound_record_id="in-failed",
            shop_id="shop-1",
            user_id="user-1",
            buyer_id="buyer-1",
            session_id="session-1",
            reply_action="reply",
            reply_text="same reply",
            reply_source="internal",
        )
        store.mark_outbox_failed(failed.outbox_id, pdd_error_code="40013")
        with store._connect() as conn:
            conn.execute("UPDATE pdd_reply_outbox SET next_retry_at = 0 WHERE id = ?", (failed.outbox_id,))

        class FailIfCalled:
            def __init__(self, shop_id, user_id):
                raise AssertionError("duplicate reply should be suppressed before sending")

        worker = OutboxWorker(store=store, sender_factory=FailIfCalled)
        summary = await worker.run_due_retries(now=store._now())

        assert summary["suppressed"] == 1
        assert summary["retried"] == 0
        assert store.get_outbox(failed.outbox_id)["status"] == "suppressed_duplicate"

    asyncio.run(scenario())


def test_outbox_worker_blocks_repeated_40013(tmp_path, monkeypatch):
    monkeypatch.setenv("PDD_SENDING_ENABLED", "true")

    async def scenario():
        store = ReliableQueueStore(tmp_path / "queue.db")
        outbox = store.create_outbox(
            trace_id="trace-40013",
            inbound_record_id="in-40013",
            shop_id="shop-1",
            user_id="user-1",
            buyer_id="buyer-1",
            session_id="session-1",
            reply_action="reply",
            reply_text="safe reply",
            reply_source="internal",
        )
        store.mark_outbox_failed(outbox.outbox_id, pdd_error_code="40013")

        class FailingSender:
            def __init__(self, shop_id, user_id):
                pass

            def send_text(self, buyer_id, reply_text):
                return {"success": True, "result": {"result": "fail", "error_code": 40013}}

        worker = OutboxWorker(store=store, sender_factory=FailingSender)
        summary = await worker.run_due_retries(now=store._now() + 3600)

        assert summary["retried"] == 1
        assert summary["failed"] == 1
        assert store.get_outbox(outbox.outbox_id)["status"] == "blocked_by_platform_policy"

    asyncio.run(scenario())


def test_outbox_worker_retries_transfer_send_failed_and_blocks_repeated_40013(tmp_path, monkeypatch):
    monkeypatch.setenv("PDD_SENDING_ENABLED", "true")

    async def scenario():
        store = ReliableQueueStore(tmp_path / "queue.db")
        outbox = store.create_outbox(
            trace_id="trace-transfer",
            inbound_record_id="in-transfer",
            shop_id="shop-1",
            user_id="user-1",
            buyer_id="buyer-1",
            session_id="session-1",
            reply_action="transfer_human",
            reply_text="transfer",
            reply_source="internal",
        )
        store.mark_outbox_failed(outbox.outbox_id, pdd_error_code="40013")

        class FailingSender:
            def __init__(self, shop_id, user_id):
                pass

            def send_text(self, buyer_id, reply_text):
                return {"success": True, "result": {"result": "fail", "error_code": 40013}}

        worker = OutboxWorker(store=store, sender_factory=FailingSender)
        summary = await worker.run_due_retries(now=store._now() + 3600)

        assert summary["retried"] == 1
        assert summary["failed"] == 1
        assert store.get_outbox(outbox.outbox_id)["status"] == "blocked_by_platform_policy"

    asyncio.run(scenario())


def test_outbox_retry_loop_retries_due_records_until_stopped(tmp_path, monkeypatch):
    monkeypatch.setenv("PDD_SENDING_ENABLED", "true")

    async def scenario():
        store = ReliableQueueStore(tmp_path / "queue.db")
        outbox = store.create_outbox(
            trace_id="trace-loop",
            inbound_record_id="in-loop",
            shop_id="shop-1",
            user_id="user-1",
            buyer_id="buyer-1",
            session_id="session-1",
            reply_action="reply",
            reply_text="safe reply",
            reply_source="internal",
        )
        store.mark_outbox_failed(outbox.outbox_id, pdd_error_code="40013")
        with store._connect() as conn:
            conn.execute("UPDATE pdd_reply_outbox SET next_retry_at = 0 WHERE id = ?", (outbox.outbox_id,))
        stop_event = asyncio.Event()
        sent = []

        class FakeSender:
            def __init__(self, shop_id, user_id):
                self.shop_id = shop_id
                self.user_id = user_id

            def send_text(self, buyer_id, reply_text):
                sent.append((self.shop_id, self.user_id, buyer_id, reply_text))
                stop_event.set()
                return {"success": True, "result": {"result": "ok"}}

        worker = OutboxWorker(store=store, sender_factory=FakeSender)
        task = asyncio.create_task(worker.run_retry_loop(stop_event=stop_event, interval_seconds=1, limit=10))
        await asyncio.wait_for(stop_event.wait(), timeout=2)
        await asyncio.wait_for(task, timeout=2)

        assert sent == [("shop-1", "user-1", "buyer-1", "safe reply")]
        assert store.get_outbox(outbox.outbox_id)["status"] == "sent"

    asyncio.run(scenario())


def test_queue_can_recover_persisted_messages_after_initial_recovery(tmp_path):
    async def scenario():
        store = ReliableQueueStore(tmp_path / "queue.db")
        queue = SimpleMessageQueue("pdd_shop-1", QueueConfig(), reliable_store=store)

        assert await queue.get(timeout=0.01) is None
        store.enqueue_inbound(queue_name="pdd_shop-1", context=_context("after reconnect", source_message_id="msg-r"))

        recovered_count = await queue.recover_persisted_now()
        recovered = await queue.get(timeout=0.1)

        assert recovered_count == 1
        assert recovered is not None
        assert recovered.context.content == "after reconnect"

    asyncio.run(scenario())


def test_reconnect_recovery_triggers_inbound_and_outbox_scan():
    async def scenario():
        calls = []

        class FakeQueue:
            async def recover_persisted_now(self):
                calls.append("inbound")
                return 2

        class FakeQueueManager:
            def get_or_create_queue(self, queue_name):
                assert queue_name == "pdd_shop-1"
                return FakeQueue()

        class FakeOutboxWorker:
            async def run_due_retries(self):
                calls.append("outbox")
                return {"retried": 1}

        summary = await trigger_reconnect_recovery(
            "pdd_shop-1",
            queue_manager_obj=FakeQueueManager(),
            outbox_worker=FakeOutboxWorker(),
        )

        assert calls == ["inbound", "outbox"]
        assert summary == {"inbound_recovered": 2, "outbox_retried": 1}

    asyncio.run(scenario())


def test_lifecycle_schedules_reconnect_recovery(monkeypatch):
    async def scenario():
        from Channel.pinduoduo.core import pdd_lifecycle

        calls = []

        async def fake_trigger(queue_name):
            calls.append(queue_name)
            return {"inbound_recovered": 0, "outbox_retried": 0}

        monkeypatch.setattr(pdd_lifecycle, "trigger_reconnect_recovery", fake_trigger)

        class Logger:
            def info(self, *args, **kwargs):
                pass

            def warning(self, *args, **kwargs):
                pass

        class Dummy(pdd_lifecycle.LifecycleMixin):
            logger = Logger()

        task = Dummy()._schedule_reconnect_recovery("pdd_shop-1")
        assert task is not None
        await task
        assert calls == ["pdd_shop-1"]

    asyncio.run(scenario())


def test_lifecycle_schedules_and_cancels_outbox_retry_loop(monkeypatch):
    async def scenario():
        from Channel.pinduoduo.core import pdd_lifecycle

        calls = []

        class FakeOutboxWorker:
            async def run_retry_loop(self, *, stop_event, interval_seconds=10.0, limit=20):
                calls.append(("started", interval_seconds, limit))
                await stop_event.wait()
                calls.append(("stopped", interval_seconds, limit))

        monkeypatch.setattr(pdd_lifecycle, "OutboxWorker", FakeOutboxWorker)

        class Logger:
            def info(self, *args, **kwargs):
                pass

            def warning(self, *args, **kwargs):
                pass

            def debug(self, *args, **kwargs):
                pass

            def error(self, *args, **kwargs):
                pass

        class Dummy(pdd_lifecycle.LifecycleMixin):
            logger = Logger()

        dummy = Dummy()
        stop_event = asyncio.Event()
        task = dummy._schedule_outbox_retry_loop("shop-1_user-1", "pdd_shop-1", stop_event)
        assert task is not None
        await asyncio.sleep(0)
        stop_event.set()
        await asyncio.wait_for(task, timeout=1)
        await dummy._cancel_mapped_task(dummy._outbox_retry_tasks, "shop-1_user-1", "outbox-retry", timeout=1)

        assert calls == [("started", 10.0, 20), ("stopped", 10.0, 20)]
        assert "shop-1_user-1" not in dummy._outbox_retry_tasks

    asyncio.run(scenario())
