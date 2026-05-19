# Concurrency Risks

## Scope

This document focuses on concurrency risks in:

- `ui/auto_reply/threads.py`
- `ui/auto_reply/manager.py`
- `Channel/pinduoduo/core/pdd_lifecycle.py`
- `Channel/pinduoduo/core/pdd_connection.py`
- `Channel/pinduoduo/core/pdd_message_handler.py`
- `Message/core/queue.py`
- `Message/core/consumer.py`
- `Message/__init__.py`
- `utils/resource_manager.py`

## Thread Model Risk

`AutoReplyThread` in `ui/auto_reply/threads.py` creates one `QThread` per account.

Inside each thread:

- `asyncio.new_event_loop()` is called.
- `asyncio.set_event_loop(self.loop)` is called.
- One `PDDChannel` instance is created.
- `self.loop.run_forever()` is called.

Risk:

- This creates a many-thread, many-event-loop architecture.
- The message managers are module-level singletons, so per-thread loops interact with global manager objects.
- If an account fails and the loop keeps running without active tasks, the thread can remain alive as a zombie worker.

Relevant code:

- `AutoReplyThread.run()`
- `AutoReplyThread.stop()`

## Event Loop Risk

`queue_manager` and `message_consumer_manager` are module-level singletons exported by `Message/__init__.py`.

`SimpleMessageQueue` creates an `asyncio.Queue` in `Message/core/queue.py` and records the running loop in `self._loop`.

`QueueManager.get_or_create_queue()` checks:

- whether an existing queue is bound to the current loop
- if not, it logs a warning and recreates the queue

Risk:

- The code already acknowledges cross-event-loop queue reuse.
- Recreating a queue may drop queued messages.
- Recreating a queue while an old `MessageConsumer` is still running can cause consumer/queue mismatch.

Relevant code:

- `SimpleMessageQueue.__init__`
- `SimpleMessageQueue.is_bound_to_current_loop()`
- `QueueManager.get_or_create_queue()`
- `QueueManager.recreate_queue()`

## Queue Isolation Risk

`LifecycleMixin.init()` uses:

```python
queue_name = f"pdd_{shop_id}"
```

Risk:

- Queue isolation is by shop only, not by account.
- If the same shop has multiple accounts or multiple threads, they share the same `queue_name`.
- `_setup_message_consumer()` may stop and recreate an existing consumer for that shop while another account is still using it.

Relevant code:

- `LifecycleMixin.init()`
- `MessageHandlerMixin._setup_message_consumer()`

## Consumer Duplication Risk

`MessageHandlerMixin._setup_message_consumer()`:

- Checks `message_consumer_manager.get_consumer(queue_name)`.
- If found, it stops and force-removes the old consumer.
- Recreates the queue.
- Creates a new consumer.
- Adds handlers from `handler_chain()`.
- Starts the consumer.

Risk:

- During reconnect, this function runs again.
- If old consumer shutdown is delayed or fails because its event loop is closed, a new consumer may start while the old one still has tasks.
- `force_remove()` removes the manager reference without proving the old consumer task is fully stopped.

Relevant code:

- `MessageHandlerMixin._setup_message_consumer()`
- `MessageConsumerManager.stop_consumer()`
- `MessageConsumerManager.force_remove()`

## Handler Re-Registration Risk

`handler_chain()` in `Message/__init__.py` returns fresh handler instances:

- `AIReplyHandler`
- `CatchAllHandler`

`_setup_message_consumer()` adds these handlers to every newly created consumer.

Risk:

- A single `MessageConsumer` does not appear to duplicate handlers by itself during normal construction.
- However, if old consumers are not fully stopped, multiple live consumers can each hold their own handler chains for the same queue name.
- This can lead to duplicate handling or inconsistent handling after reconnect.

Relevant code:

- `handler_chain()`
- `MessageConsumer.add_handler()`
- `MessageHandlerMixin._setup_message_consumer()`

## Semaphore Risk

There are two important semaphores:

1. `PDDChannel.message_semaphore` in `pdd_channel.py`
2. `MessageConsumer.semaphore` in `consumer.py`

Risk:

- `message_semaphore` limits concurrent WebSocket message parsing for a `PDDChannel` instance.
- `MessageConsumer.semaphore` limits concurrent consumer handler execution.
- Both are created in a specific event loop context.
- If objects are reused across event loops, semaphores can become loop-affinity hazards similar to queues.

Relevant code:

- `PDDChannel.__init__`
- `MessageConsumer.__init__`

## Task Lifecycle Risk

The code creates tasks in several places:

| File | Function | Task |
|---|---|---|
| `pdd_lifecycle.py` | `start_account()` | `_connect_with_retry()` or `_connect_single_attempt()` |
| `pdd_lifecycle.py` | `init()` | `_heartbeat_loop()` |
| `pdd_lifecycle.py` | `init()` | `_message_loop()` |
| `pdd_lifecycle.py` | `init()` | `stop_event.wait()` |
| `pdd_lifecycle.py` | `_message_loop()` | `_process_websocket_message_concurrent()` per message |
| `consumer.py` | `start()` | `_consume_loop()` |
| `consumer.py` | `_consume_loop()` | `_process_message()` per queued message |
| `resource_manager.py` | weakref callback | `_cleanup_reference()` |

Risk:

- `start_account()` cancels an existing reconnect task but does not await its completion before deleting it.
- `AutoReplyThread.stop()` cancels all tasks in the loop but does not gather/await them before stopping the loop.
- Per-message task creation can grow quickly under high traffic.

Relevant code:

- `LifecycleMixin.start_account()`
- `AutoReplyThread.stop()`
- `LifecycleMixin._message_loop()`
- `MessageConsumer._consume_loop()`

## WebSocket Close Risk

`ConnectionMixin._safe_close_websocket()` calls `close()` but does not explicitly call `wait_closed()`.

`WebSocketResourceManager.cleanup_all()` also calls `close()` but does not explicitly wait for close completion beyond awaiting `close()` when it is a coroutine.

Risk:

- WebSocket close handshake may not fully complete before loop shutdown.
- Pending close tasks can remain during thread shutdown.

Relevant code:

- `ConnectionMixin._safe_close_websocket()`
- `WebSocketResourceManager.cleanup_all()`

## Resource Manager Risk

`WebSocketResourceManager.register_websocket()` creates a weakref callback that calls:

```python
asyncio.create_task(self._cleanup_reference(ref))
```

Risk:

- Weakref callbacks can run when no event loop is running in the current thread.
- If the loop is closed, this can raise runtime errors.
- Cleanup side effects are triggered by garbage collection timing, which is nondeterministic.

Relevant code:

- `WebSocketResourceManager.register_websocket()`

## Shared State Table

| Object | Scope | Current Risk |
|---|---|---|
| `self.ws` | `PDDChannel` instance | Single field. Safe only if one channel instance handles one account. |
| `self._stop_event` | `PDDChannel` instance | Single field overwritten by latest account in same instance. |
| `self._stop_events` | `PDDChannel` instance dict | Better per-account isolation by `connection_key`. |
| `self._reconnect_tasks` | `PDDChannel` instance dict | Per-account map, but old task cancel is not always awaited. |
| `self._heartbeat_tasks` | `PDDChannel` instance dict | Per-account map, cleanup can clear all heartbeat tasks in the instance. |
| `self.processing_tasks` | `PDDChannel` instance set | Not per-account isolated. |
| `queue_manager` | Module singleton | Cross-event-loop global manager. |
| `message_consumer_manager` | Module singleton | Cross-event-loop global consumer manager. |
| `redis_manager` | Module singleton | Current compatibility implementation weakens lock semantics. |
| `db_manager` | Global database facade | Needs thread/SQLite session safety review. |
| `ConnectionStatusManager` | DI singleton | Uses `RLock`; intended global shared status. |

## Main Risk Summary

The most important concurrency risk is the mismatch between:

- per-account `QThread` and per-thread `asyncio` event loop
- global `queue_manager`
- global `message_consumer_manager`
- shop-level `queue_name`

This can create cross-loop queue recreation, duplicated consumer lifecycle, and stale tasks after reconnect.
