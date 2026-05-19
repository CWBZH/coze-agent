# Deadlock and Crash Analysis

## Scope

This document analyzes likely causes of freeze, crash, or apparent machine hang after WebSocket disconnect/reconnect events.

This is based on static code analysis only.

## Most Likely Root Causes

### 1. Cross-Event-Loop Queue and Consumer Recreation

Probability: High

Trigger condition:

- Same shop reconnects quickly.
- Multiple accounts for the same shop are started.
- UI stop/start overlaps with reconnect.

Related code:

- `LifecycleMixin.init()` in `Channel/pinduoduo/core/pdd_lifecycle.py`
- `MessageHandlerMixin._setup_message_consumer()` in `Channel/pinduoduo/core/pdd_message_handler.py`
- `QueueManager.get_or_create_queue()` in `Message/core/queue.py`
- `MessageConsumerManager.stop_consumer()` in `Message/core/consumer.py`

Code pattern:

- `queue_name = f"pdd_{shop_id}"`
- `_setup_message_consumer()` stops existing consumer.
- Queue is recreated.
- New consumer is created and started.
- Existing queues may be bound to another event loop.

Runtime symptoms:

- Messages stop being consumed.
- Repeated logs about queue bound to another event loop.
- Consumer stopped unexpectedly.
- Reconnect creates new consumers while old processing tasks still exist.
- Memory and task count grow.

Verification:

- Log `queue_name`, `id(queue)`, `id(asyncio.get_running_loop())`.
- Log `id(consumer)`, `id(consumer.consumer_task)`.
- Log queue recreation count per `queue_name`.
- Log old consumer stop duration and result.

Suggested log points:

- Before and after `queue_manager.recreate_queue(queue_name)`.
- Before and after `message_consumer_manager.stop_consumer(queue_name)`.
- In `MessageConsumer._consume_loop()` when it starts and stops.

Fix direction:

- Use account-level queue names such as `pdd_{shop_id}_{user_id}`.
- Make consumer creation idempotent.
- Avoid queue recreation during reconnect if an equivalent healthy queue exists in the same event loop.

### 2. Reconnect Task Cancelled Without Awaiting Completion

Probability: High

Trigger condition:

- `start_account()` is called while a reconnect task for the same `connection_key` already exists.

Related code:

- `LifecycleMixin.start_account()` in `Channel/pinduoduo/core/pdd_lifecycle.py`

Code pattern:

- Existing reconnect task is cancelled.
- It is removed from `_reconnect_tasks`.
- The code does not wait for that task to actually exit.
- A new reconnect task is created.

Runtime symptoms:

- Old task continues cleanup while new task is already connecting.
- New WebSocket may be closed by old cleanup.
- New consumer may be stopped by old cleanup.
- Status may move backward from `CONNECTED` to `DISCONNECTED` or `SUSPENDED`.

Verification:

- Add task ID and lifecycle logging:
  - created
  - cancel requested
  - cancel completed
  - finally cleanup completed
- Log `connection_key` and `id(task)` for every reconnect task.

Fix direction:

- Add a per-account lifecycle lock.
- Cancel old task and await it with timeout before creating the next one.
- Track a generation ID so stale tasks cannot clean up newer sessions.

### 3. Thread Stop Cancels Tasks But Does Not Await Shutdown

Probability: Medium-High

Trigger condition:

- User stops auto-reply.
- Final connection failure calls `thread.stop()`.
- Application exits while tasks are still active.

Related code:

- `AutoReplyThread.stop()` in `ui/auto_reply/threads.py`
- `AutoReplyThread.run()` finally block in `ui/auto_reply/threads.py`

Code pattern:

- Calls `self.channel.request_stop()`.
- Iterates `asyncio.all_tasks(self.loop)`.
- Calls `task.cancel()`.
- Calls `self.loop.call_soon_threadsafe(self.loop.stop)`.
- Does not gather and await pending tasks before stopping the loop.

Runtime symptoms:

- Pending tasks destroyed.
- WebSocket close not complete.
- Consumer cleanup incomplete.
- Event loop closed while callbacks still exist.
- Later start sees stale manager state.

Verification:

- Before loop stop, log pending task count and task names/reprs.
- After cleanup, log pending task count again.
- Track whether `stop_all_connections()` completes.

Fix direction:

- Introduce a shutdown coroutine.
- Await `channel.stop_all_connections()`.
- Gather pending tasks with timeout.
- Only stop and close the loop after cleanup completes.

### 4. Single-Field WebSocket State in `PDDChannel`

Probability: Medium

Trigger condition:

- A `PDDChannel` instance is reused for more than one account.
- Future refactor attempts to manage multiple accounts from one channel instance.

Related code:

- `PDDChannel.__init__` in `Channel/pinduoduo/pdd_channel.py`
- `LifecycleMixin.init()` in `Channel/pinduoduo/core/pdd_lifecycle.py`
- `LifecycleMixin.stop_account()` in `Channel/pinduoduo/core/pdd_lifecycle.py`

Code pattern:

- `self.ws` is a single field.
- `self._stop_event` is a single field.
- `self.processing_tasks` is one set for the whole channel instance.

Runtime symptoms:

- Stop one account closes another account's WebSocket.
- Processing tasks for different accounts are cancelled together.
- Connection status and resource cleanup become inconsistent.

Verification:

- Log `id(self)`, `connection_key`, and `id(self.ws)` on every connect and stop.
- Confirm whether any `PDDChannel` instance handles multiple connection keys.

Fix direction:

- Introduce `ConnectionSession`.
- Store `websocket`, stop event, heartbeat task, message task, reconnect task, and processing tasks inside that session.

### 5. WebSocket Close and Weakref Cleanup Are Not Fully Deterministic

Probability: Medium

Trigger condition:

- Frequent disconnects.
- Event loop closes while WebSocket cleanup callbacks are pending.
- Garbage collection runs after loop shutdown.

Related code:

- `ConnectionMixin._safe_close_websocket()` in `Channel/pinduoduo/core/pdd_connection.py`
- `WebSocketResourceManager.register_websocket()` in `utils/resource_manager.py`
- `WebSocketResourceManager.cleanup_all()` in `utils/resource_manager.py`

Code pattern:

- `close()` is called.
- Explicit `wait_closed()` is not used.
- Weakref callback calls `asyncio.create_task()`.

Runtime symptoms:

- Runtime errors from create_task when no loop is running.
- Pending close operations.
- Resource manager still reports active or registered connections.

Verification:

- Log resource manager `health_check()` before and after cleanup.
- Log loop running/closed state in weakref cleanup callback.
- Log WebSocket close state before and after close.

Fix direction:

- Explicitly wait for close completion where supported.
- Avoid creating async tasks inside weakref callbacks unless a known running loop is available.

## Diagnostic Logging Recommendations

Add logs at component boundaries. Recommended fields:

- `connection_key`
- `shop_id`
- `user_id`
- `username`
- `id(PDDChannel)`
- `id(asyncio.get_running_loop())`
- `id(websocket)`
- `queue_name`
- `id(queue)`
- `id(consumer)`
- `id(task)`
- task state
- queue size
- processing task count
- reconnect attempt
- heartbeat failure count

Recommended log points:

| Location | Log |
|---|---|
| `AutoReplyManager.start_auto_reply()` | account key, thread state, debounce decision |
| `AutoReplyThread.run()` | loop id, thread id, channel id |
| `AutoReplyThread.stop()` | pending task count before cancel |
| `LifecycleMixin.start_account()` | connection key, existing reconnect task id |
| `ConnectionMixin._connect_with_retry()` | attempt number, delay, stop event state |
| `LifecycleMixin.init()` | queue name, websocket id, task ids |
| `MessageHandlerMixin._setup_message_consumer()` | existing consumer id, queue recreation, new consumer id |
| `QueueManager.get_or_create_queue()` | loop id, queue id, recreated flag |
| `MessageConsumer._consume_loop()` | started/stopped, queue id, loop id |
| `LifecycleMixin._cleanup_resources()` | processing task count, consumer stop result, ws state |

## Verification Checklist

Use logs only. Do not connect to real PDD during audit unless explicitly allowed later.

- Confirm one `AutoReplyThread` per account.
- Confirm one `PDDChannel` instance per account.
- Confirm no `PDDChannel` instance handles multiple connection keys.
- Confirm queue names are unique enough for the runtime model.
- Confirm no queue is recreated while a consumer is still alive.
- Confirm every reconnect task exits before a replacement task starts.
- Confirm every stopped thread drains pending tasks before loop close.
- Confirm `processing_tasks` count returns to zero after stop.
- Confirm resource manager has zero active WebSocket references after stop.

## Crash and Freeze Triage Order

1. Check for repeated queue recreation and cross-loop warnings.
2. Check for duplicate consumers for the same `queue_name`.
3. Check pending task count before loop close.
4. Check reconnect task overlap by `connection_key`.
5. Check WebSocket resource cleanup completion.
6. Check synchronous DB/API calls blocking the account event loop.
