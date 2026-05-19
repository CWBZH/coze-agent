# Refactor Plan

## Goals

The target is to make the Pinduoduo WebSocket customer-service runtime stable under disconnect, reconnect, stop/start, and application shutdown.

The plan is split into:

- P0: Immediate containment
- P1: Stability refactor
- P2: Architecture normalization

## Non-Goals

This plan does not require changing business reply logic first.

Business behavior should remain unchanged while lifecycle and concurrency boundaries are stabilized.

## P0: Immediate Containment

### P0.1 Add lifecycle diagnostics

Scope:

- `AutoReplyManager`
- `AutoReplyThread`
- `LifecycleMixin`
- `MessageHandlerMixin`
- `QueueManager`
- `MessageConsumer`

Add logs for:

- connection key
- loop id
- task id
- queue id
- consumer id
- processing task count
- reconnect attempt

Risk:

- More logs may increase log volume.

Rollback:

- Disable by log level or remove only diagnostic statements.

### P0.2 Prevent duplicate reconnect tasks

Scope:

- `LifecycleMixin.start_account()`

Change:

- When an existing reconnect task exists for `connection_key`, cancel it and await completion with timeout before creating a new task.
- Add per-account lifecycle lock or equivalent guard.

Risk:

- Start may wait longer when old task is stuck.

Rollback:

- Revert to previous cancel-only behavior, keeping diagnostics.

### P0.3 Make queue names account-level

Scope:

- `LifecycleMixin.init()`
- `_cleanup_resources(queue_name)`
- `_setup_message_consumer(queue_name)`

Change:

- Replace shop-only queue name with account-level queue name:
  - current: `pdd_{shop_id}`
  - target: `pdd_{shop_id}_{user_id}`

Risk:

- Any code that assumes shop-level queue name must be updated consistently.

Rollback:

- Revert queue name format.

### P0.4 Make consumer setup idempotent

Scope:

- `MessageHandlerMixin._setup_message_consumer()`
- `MessageConsumerManager.create_consumer()`
- `MessageConsumer.start()`

Change:

- If a consumer exists, is running, and belongs to the same loop, do not recreate it.
- Avoid unconditional queue recreation during reconnect.
- If the old consumer is stale, stop and await it before replacement.

Risk:

- Existing stale consumer detection must be accurate.

Rollback:

- Fall back to forced recreate while keeping account-level queue names.

### P0.5 Limit task growth

Scope:

- `LifecycleMixin._message_loop()`
- `MessageConsumer._consume_loop()`

Change:

- Enforce a maximum number of `processing_tasks`.
- Enforce a maximum number of active consumer handler tasks.
- When limits are exceeded, log and degrade to skip, delay, or transfer-human depending on business policy.

Risk:

- Some messages may be delayed or skipped under overload.

Rollback:

- Increase limits or disable limit enforcement.

## P1: Stability Refactor

### P1.1 Introduce account-level connection state object

Scope:

- New connection lifecycle module or internal class.
- Existing `PDDChannel` lifecycle code.

Create `ConnectionSession` with:

- `connection_key`
- `shop_id`
- `user_id`
- `username`
- `websocket`
- `stop_event`
- `reconnect_task`
- `heartbeat_task`
- `message_task`
- `processing_tasks`
- `queue_name`
- `generation`

Risk:

- Requires careful migration from `self.ws`, `self._stop_event`, and task maps.

Rollback:

- Keep old `PDDChannel` fields while session object is introduced behind an adapter.

### P1.2 Normalize graceful shutdown

Scope:

- `AutoReplyThread.stop()`
- `LifecycleMixin.stop_account()`
- `LifecycleMixin.stop_all_connections()`
- `ConnectionMixin._safe_close_websocket()`

Change:

- Stop sequence:
  1. set stop event
  2. cancel reconnect/heartbeat/message tasks
  3. await cancellation
  4. close websocket
  5. wait for close completion where supported
  6. stop consumer
  7. clear processing tasks
  8. remove session

Risk:

- Shutdown may take longer.

Rollback:

- Keep timeout caps and fallback forced cleanup.

### P1.3 Fixed worker pool

Scope:

- `MessageConsumer`

Change:

- Replace unbounded per-message `asyncio.create_task()` with a bounded worker pool.
- Workers read from queue and process messages.

Risk:

- Requires queue drain semantics and stop behavior definition.

Rollback:

- Keep existing task-per-message model behind a feature flag.

### P1.4 Queue and consumer ownership model

Scope:

- `QueueManager`
- `MessageConsumerManager`

Change:

- Track owner loop id and owner connection key.
- Reject accidental cross-loop use unless explicitly recreated through lifecycle code.
- Add health methods:
  - queue size
  - consumer running
  - worker count
  - owner loop id

Risk:

- More explicit errors may surface hidden bugs.

Rollback:

- Log warnings first, enforce after validation.

### P1.5 Real lock semantics

Scope:

- `database/redis_manager.py`
- `AIReplyHandler`
- `MessagePipeline`

Change:

- Replace no-op lock compatibility behavior with a real backend:
  - Redis
  - SQLite-backed lock table
  - or in-process lock only for desktop mode

Risk:

- Behavior changes for human lock and inference lock.

Rollback:

- Keep compatibility mode selectable by config.

## P2: Architecture Normalization

### P2.1 WebSocketManager

Responsibility:

- Own all connection sessions.
- Enforce one session per account.
- Provide start/stop/restart/status APIs.

Risk:

- Medium refactor across UI and channel layer.

Rollback:

- Keep `PDDChannel` facade and delegate to manager internally.

### P2.2 ConsumerManager and QueueManager boundary

Responsibility:

- QueueManager owns queue creation and queue health.
- ConsumerManager owns worker lifecycle.
- Neither should directly depend on PyQt.

Risk:

- Requires tests around message ordering and stop/start.

Rollback:

- Keep old module-level facades in `Message/__init__.py`.

### P2.3 StatusManager and Metrics

Responsibility:

- Connection state
- reconnect count
- last connect time
- last message time
- last heartbeat time
- queue backlog
- processing task count
- consumer running state

Risk:

- Metrics can diverge if not updated consistently.

Rollback:

- Start as read-only diagnostic snapshot.

### P2.4 HealthCheck

Add health checks for:

- WebSocket session count
- per-account connection status
- queue backlog
- consumer running state
- DB read/write
- FastGPT availability
- notification backend availability

Risk:

- Some checks may call external systems; keep external checks optional.

Rollback:

- Keep local-only health checks.

### P2.5 Linux service split

Target split:

| Component | Responsibility |
|---|---|
| PyQt client | Login, account management, operator UI |
| WebSocket worker | PDD long connections and inbound message normalization |
| Message worker | Queue consumption, AI pipeline, reply sending |
| API service | Admin API, health, config, status |
| DB | Durable state |
| Redis or lock backend | Locks, rate limits, queue coordination |

Risk:

- Requires deployment, config, secret, and observability redesign.

Rollback:

- Keep desktop mode as fallback runtime until Linux worker is validated.

## Suggested Acceptance Criteria

P0:

- Repeated start clicks do not create duplicate reconnect tasks.
- Disconnect/reconnect does not recreate a queue used by another running account.
- Stop account drains tasks before loop close.
- No pending task warnings during controlled stop.

P1:

- Each account has exactly one `ConnectionSession`.
- Queue and consumer are owned by one account/session.
- Shutdown can be called repeatedly without errors.
- Worker task count remains bounded under message burst.

P2:

- WebSocket runtime can run headless.
- Health endpoint exposes connection, queue, consumer, and dependency state.
- PyQt no longer owns the core long-running service lifecycle.
