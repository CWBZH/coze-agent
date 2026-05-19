# Pinduoduo WebSocket Lifecycle

## Scope

This document describes the current WebSocket lifecycle based on these files:

- `ui/auto_reply/manager.py`
- `ui/auto_reply/threads.py`
- `Channel/pinduoduo/pdd_channel.py`
- `Channel/pinduoduo/core/pdd_connection.py`
- `Channel/pinduoduo/core/pdd_lifecycle.py`
- `Channel/pinduoduo/core/pdd_message_handler.py`
- `Message/__init__.py`
- `Message/core/queue.py`
- `Message/core/consumer.py`
- `Message/handlers/ai_handler.py`
- `Message/core/pipeline.py`

## Lifecycle Summary

### 1. UI Start

`AutoReplyManager.start_auto_reply(account_data)` in `ui/auto_reply/manager.py` is the high-level start entry.

It:

- Builds `account_key` from `channel_name`, `shop_id`, and `username`.
- Checks `_suspended_until`.
- Applies `_start_cooldown_seconds`.
- Checks `running_accounts`.
- Creates `AutoReplyThread(account_data)`.
- Connects `connection_success`, `connection_failed`, and `finished` signals.
- Starts the thread.

### 2. Thread and Event Loop Creation

`AutoReplyThread.run()` in `ui/auto_reply/threads.py`:

- Creates a new event loop with `asyncio.new_event_loop()`.
- Binds it with `asyncio.set_event_loop(self.loop)`.
- Creates `self.channel = PDDChannel()`.
- Creates a task for `self.channel.start_account(...)`.
- Stores it as `self._start_task`.
- Calls `self.loop.run_forever()`.

This means every started account gets a dedicated `QThread` and a dedicated `asyncio` event loop.

### 3. Channel Startup

`LifecycleMixin.start_account()` in `Channel/pinduoduo/core/pdd_lifecycle.py`:

- Loads account info through `db_manager.get_account(self.channel_name, shop_id, user_id)`.
- Computes `connection_key = f"{shop_id}_{user_id}"`.
- Updates `ConnectionStatusManager` to `CONNECTING`.
- Cancels and removes an existing reconnect task for the same key if present.
- Creates a per-account stop event in `self._stop_events[connection_key]`.
- Assigns `self._stop_event` to that event.
- Creates `_connect_with_retry()` task when auto reconnect is enabled.
- Stores the task in `self._reconnect_tasks[connection_key]`.

### 4. Retry Strategy

`ConnectionMixin._connect_with_retry()` in `Channel/pinduoduo/core/pdd_connection.py`:

- Uses `self.reconnect_config.max_attempts`.
- Marks status as `RECONNECTING` on retries.
- Calls `_connect_single_attempt()`.
- On failure, computes delay:
  - `initial_delay * (backoff_factor ** attempt)`
  - capped by `max_delay`
- Sleeps in 0.1-second chunks so it can notice `stop_event`.
- On final failure, marks status as `SUSPENDED`, calls `on_failure()`, and sets `stop_event`.

Current retry defaults are in `Channel/pinduoduo/core/pdd_config.py`:

- `max_attempts = 3`
- `initial_delay = 5.0`
- `max_delay = 45.0`
- `backoff_factor = 3.0`
- `enable_auto_reconnect = True`

### 5. Single Attempt and Authentication

`_connect_single_attempt()` calls `init()`.

`LifecycleMixin.init()`:

- Creates or retrieves `stop_event`.
- Calls `GetToken(shop_id, user_id).get_token()` through `asyncio.to_thread()`.
- Creates `queue_name = f"pdd_{shop_id}"`.
- Calls `_setup_message_consumer(queue_name)`.
- Builds WebSocket URL:
  - `self.base_url`
  - `access_token`
  - `role = mall_cs`
  - `client = web`
  - `version = self.API_VERSION`

`self.base_url` is defined in `PDDChannel.__init__` as:

- `wss://m-ws.pinduoduo.com/`

### 6. WebSocket Connection

`LifecycleMixin.init()` opens the connection:

```python
async with websockets.connect(
    full_url,
    ping_interval=60,
    ping_timeout=30,
    max_size=10**7,
    compression=None,
    close_timeout=10
) as websocket:
```

After connection:

- Assigns `self.ws = websocket`.
- Registers the WebSocket in `self.resource_manager`.
- Marks status as `CONNECTED`.
- Calls `on_success()`.

### 7. Task Creation

Inside `init()`:

- Creates heartbeat task when `self.heartbeat_config.enable_heartbeat` is true.
- Creates message task for `_message_loop(...)`.
- Creates stop task for `stop_event.wait()`.
- Waits for first completed task with `asyncio.wait(..., return_when=asyncio.FIRST_COMPLETED)`.

### 8. Heartbeat Loop

`_heartbeat_loop()`:

- Runs while stop event is not set.
- Calls `await websocket.ping()`.
- Tracks `consecutive_failures`.
- Sleeps `self.heartbeat_config.heartbeat_interval`.
- On repeated failures, updates status to `ERROR`, calls `on_failure()`, and breaks.

Current heartbeat defaults:

- `enable_heartbeat = True`
- `heartbeat_interval = 30.0`
- `heartbeat_timeout = 10.0`
- `max_heartbeat_failures = 3`

### 9. Message Receive Loop

`_message_loop()`:

- Runs `async for message in websocket`.
- Checks stop event.
- Creates one task per message:
  - `_process_websocket_message_concurrent(...)`
- Adds the task to `self.processing_tasks`.
- Adds `task.add_done_callback(self.processing_tasks.discard)`.

`_process_websocket_message_concurrent()`:

- Uses `async with self.message_semaphore`.
- Calls `_process_websocket_message()`.

### 10. Message Parsing and Queueing

`MessageHandlerMixin._process_websocket_message()`:

- Ignores empty messages.
- Parses JSON.
- Detects `from_role == "mall_cs"`.
  - For mall customer-service messages, renews human lock through `redis_manager.renew_human_lock()`.
  - Does not enqueue the message.
- Converts payload into `PDDChatMessage`.
- Converts that into `Context`.
- Routes immediate message types to `_handle_immediate_message()`.
- Queues normal message types by calling:
  - `put_message(queue_name, context)`

### 11. Queue and Consumer

`Message.put_message()`:

- Calls `queue_manager.get_or_create_queue(queue_name)`.
- Calls `queue.put(context)`.

`MessageConsumer._consume_loop()`:

- Gets queue through `queue_manager.get_or_create_queue(self.queue_name)`.
- Runs while `self.running`.
- Calls `queue.get(timeout=1.0)`.
- Creates `_process_message(wrapper)` tasks.

`_process_message()`:

- Builds metadata from `Context`.
- Iterates handlers.
- Calls `handler.can_handle(context)`.
- Calls `handler.handle(context, metadata)`.

### 12. AI Reply and Send

`handler_chain()` currently creates:

- `AIReplyHandler`
- `CatchAllHandler`

`AIReplyHandler.handle()`:

- Handles image interception.
- Checks human lock through `redis_manager.is_human_locked()`.
- Checks static rules through `redis_manager.get_static_rules()`.
- Acquires inference lock through `redis_manager.acquire_inference_lock()`.
- Calls `_get_ai_reply()`.

`_get_ai_reply()`:

- Lazily creates `MessagePipeline`.
- Calls `pipeline.process(message)`.

`MessagePipeline.process()`:

- Gets or creates conversation.
- Checks pending human / human handling states.
- Checks keyword rules.
- Builds FastGPT messages.
- Calls FastGPT through `_call_fastgpt_async()`.
- Handles fallback and transfer-human notification.

`AIReplyHandler._send_reply()`:

- Imports `SendMessage`.
- Calls `sender.send_text(from_uid, reply)` through `asyncio.to_thread()`.

### 13. Stop and Cleanup

High-level stop path:

- `AutoReplyManager.stop_auto_reply()`
- `AutoReplyThread.stop()`
- `PDDChannel.request_stop()`
- Cancel all tasks in the event loop.
- Stop event loop.
- `AutoReplyThread.run()` finally calls `self.channel.stop_all_connections()`.

`stop_all_connections()`:

- Sets stop events.
- Cancels reconnect tasks.
- Cancels heartbeat tasks.
- Calls `_safe_close_websocket(self.ws)`.
- Clears `_stop_events`.

`_cleanup_resources(queue_name)`:

- Calls `cleanup_processing_tasks()`.
- Calls `_cleanup_heartbeat_tasks()`.
- Calls `resource_manager.cleanup_all()`.
- Calls `message_consumer_manager.stop_consumer(queue_name)`.
- Sets `self.ws = None`.

## Sequence Diagram

```mermaid
sequenceDiagram
    participant UI as PyQt UI
    participant ARM as AutoReplyManager
    participant ART as AutoReplyThread
    participant LOOP as asyncio loop
    participant PDD as PDDChannel
    participant LIFE as LifecycleMixin
    participant CONN as ConnectionMixin
    participant WS as PDD WebSocket
    participant MH as MessageHandlerMixin
    participant QM as queue_manager
    participant CM as message_consumer_manager
    participant C as MessageConsumer
    participant AI as AIReplyHandler
    participant PIPE as MessagePipeline
    participant SEND as SendMessage

    UI->>ARM: start_auto_reply(account_data)
    ARM->>ART: create and start QThread
    ART->>LOOP: new_event_loop + set_event_loop
    ART->>PDD: PDDChannel()
    ART->>LOOP: create_task(PDD.start_account)
    ART->>LOOP: run_forever()

    PDD->>LIFE: start_account(shop_id, user_id)
    LIFE->>LOOP: create_task(_connect_with_retry)
    LIFE->>CONN: _connect_with_retry()
    CONN->>LIFE: _connect_single_attempt()
    LIFE->>LIFE: init()
    LIFE->>MH: _setup_message_consumer(queue_name)
    MH->>QM: recreate_queue(queue_name)
    MH->>CM: create_consumer(queue_name)
    MH->>CM: start_consumer(queue_name)

    LIFE->>WS: websockets.connect(full_url)
    LIFE->>LOOP: create_task(_heartbeat_loop)
    LIFE->>LOOP: create_task(_message_loop)
    LIFE->>LOOP: create_task(stop_event.wait)

    WS-->>LIFE: inbound message
    LIFE->>LOOP: create_task(_process_websocket_message_concurrent)
    LIFE->>MH: _process_websocket_message
    MH->>QM: put_message(queue_name, context)

    C->>QM: queue.get(timeout=1)
    C->>AI: handle(context, metadata)
    AI->>PIPE: process(message)
    PIPE-->>AI: reply / transfer / skip
    AI->>SEND: send_text via asyncio.to_thread()

    UI->>ARM: stop_auto_reply(account_data)
    ARM->>ART: stop()
    ART->>PDD: request_stop()
    ART->>LOOP: cancel all tasks + stop loop
    ART->>PDD: stop_all_connections()
```
