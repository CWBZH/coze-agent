import asyncio
import time

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from bridge.context import ChannelType, Context, ContextType
from Message.core.consumer import MessageConsumer
from Message.core.handlers import MessageHandler
from Message.core.session_debounce import SessionMessageDebouncer
from Message.models.queue_models import MessageWrapper


def _context(
    message: str,
    *,
    source_message_id: str,
    from_uid: str = "buyer-1",
    shop_id: str = "shop-1",
    user_id: str = "user-1",
    msg_type: ContextType = ContextType.TEXT,
) -> Context:
    return Context.create_pinduoduo_context(
        content=message,
        msg_id=source_message_id,
        from_uid=from_uid,
        to_uid="seller-1",
        shop_id=shop_id,
        user_id=user_id,
        username="seller",
        user_msg_type=msg_type,
        channel_type=ChannelType.PINDUODUO,
        trace_id=f"trace-{source_message_id}",
        source_message_id=source_message_id,
        queue_name=f"pdd_{shop_id}",
        message_type=msg_type.value,
    )


def test_text_debouncer_merges_same_session_short_burst_once():
    async def scenario():
        enqueued = []

        async def enqueue(queue_name, context):
            enqueued.append((queue_name, context))
            return f"queued-{len(enqueued)}"

        debouncer = SessionMessageDebouncer(window_seconds=0.03)
        await debouncer.submit("pdd_shop-1", _context("这个", source_message_id="m1"), enqueue)
        await debouncer.submit("pdd_shop-1", _context("一包多少张", source_message_id="m2"), enqueue)
        await asyncio.sleep(0.08)

        assert len(enqueued) == 1
        queued_context = enqueued[0][1]
        assert queued_context.content == "这个\n一包多少张"
        assert getattr(queued_context.kwargs, "merged_from_burst") is True
        assert getattr(queued_context.kwargs, "burst_message_count") == 2
        assert getattr(queued_context.kwargs, "burst_source_message_ids") == ["m1", "m2"]

    asyncio.run(scenario())


def test_non_text_message_bypasses_debounce():
    async def scenario():
        enqueued = []

        async def enqueue(queue_name, context):
            enqueued.append((queue_name, context))
            return f"queued-{len(enqueued)}"

        debouncer = SessionMessageDebouncer(window_seconds=0.05)
        await debouncer.submit(
            "pdd_shop-1",
            _context("商品卡片", source_message_id="card-1", msg_type=ContextType.GOODS_CARD),
            enqueue,
        )

        assert len(enqueued) == 1
        assert enqueued[0][1].content == "商品卡片"
        assert getattr(enqueued[0][1].kwargs, "merged_from_burst", False) is False

    asyncio.run(scenario())


def test_consumer_serializes_same_session_even_with_concurrent_workers():
    async def scenario():
        timeline = []

        class SlowHandler(MessageHandler):
            def can_handle(self, context):
                return True

            async def handle(self, context, metadata):
                timeline.append(("start", context.content, asyncio.get_running_loop().time()))
                await asyncio.sleep(0.03)
                timeline.append(("end", context.content, asyncio.get_running_loop().time()))
                return True

        consumer = MessageConsumer("pdd_shop-1", max_concurrent=2)
        consumer.add_handler(SlowHandler())
        wrappers = [
            MessageWrapper(message_id="w1", context=_context("first", source_message_id="m1"), timestamp=time.time()),
            MessageWrapper(message_id="w2", context=_context("second", source_message_id="m2"), timestamp=time.time()),
        ]

        await asyncio.gather(*(consumer._process_message(wrapper) for wrapper in wrappers))

        assert [item[:2] for item in timeline] == [
            ("start", "first"),
            ("end", "first"),
            ("start", "second"),
            ("end", "second"),
        ]

    asyncio.run(scenario())


def test_consumer_allows_different_sessions_to_process_in_parallel():
    async def scenario():
        starts = {}
        ends = {}

        class SlowHandler(MessageHandler):
            def can_handle(self, context):
                return True

            async def handle(self, context, metadata):
                starts[context.content] = asyncio.get_running_loop().time()
                await asyncio.sleep(0.04)
                ends[context.content] = asyncio.get_running_loop().time()
                return True

        consumer = MessageConsumer("pdd_shop-1", max_concurrent=2)
        consumer.add_handler(SlowHandler())
        wrappers = [
            MessageWrapper(
                message_id="w1",
                context=_context("first", source_message_id="m1", from_uid="buyer-1"),
                timestamp=time.time(),
            ),
            MessageWrapper(
                message_id="w2",
                context=_context("second", source_message_id="m2", from_uid="buyer-2"),
                timestamp=time.time(),
            ),
        ]

        await asyncio.gather(*(consumer._process_message(wrapper) for wrapper in wrappers))

        assert starts["second"] < ends["first"]

    asyncio.run(scenario())
