# T084-A PushPlus / Clawbot Transfer Notification Audit

Date: 2026-05-20

Scope: read-only audit of current manual-transfer notification behavior, with fake test design. No Python code was changed for this task.

Implementation update:

- T084-B adds `HeadlessNotificationService` for Linux/headless PushPlus delivery.
- `HEADLESS_MODE=1` now uses `HeadlessNotificationService` when PushPlus is enabled and token is configured.
- If PushPlus is disabled or token is missing, headless mode falls back to `DummyNotificationService` with an explicit warning.
- PushPlus notification content now uses a controlled whitelist and max 500-character previews for the latest buyer / seller-or-AI text.
- PushPlus provider response logs now record status, provider code, response length, and response hash instead of raw response body.
- T084-D extends transfer notification metadata propagation for image, video, keyword transfer, missing dataset, FastGPT failure/empty, unsafe reply, SendMessage failed, and unknown delivery paths.

## 1. 当前通知链路

### 1.1 Desktop / PyQt path

Current desktop runtime uses the DI container to inject `UINotificationService`.

Flow:

```text
AIReplyHandler / MessagePipeline / AutoReplyManager
  -> container.get("NotificationService")
  -> UINotificationService.alert_human_fallback(...)
  -> PyQt signal: global_signal_bus.human_fallback_signal.emit(...)
  -> PushPlus async thread: _notify_pushplus_async(...)
  -> PushPlusNotifier.send(...)
  -> http://www.pushplus.plus/send
```

Relevant files:

- `core/di_container.py`
- `core/notification.py`
- `ui/notification_impl.py`
- `core/pushplus_notifier.py`
- `core/human_alert_context.py`

PushPlus configuration comes from `core/config.py`:

- `PUSHPLUS_ENABLED`
- `PUSHPLUS_TOKEN`
- `PUSHPLUS_CHANNEL`, default `clawbot`
- `PUSHPLUS_TEMPLATE`
- `PUSHPLUS_TIMEOUT`

### 1.2 Handler / pipeline call sites

Current manual-transfer notification callers are split across:

- `Message/handlers/ai_handler.py`
- `Message/core/pipeline.py`
- `ui/auto_reply/manager.py`

Common call shape:

```text
notification_service.alert_human_fallback(
    shop_id=...,
    user_id=...,
    reason=...,
    alert_level=...
)
```

The notification interface currently only accepts `shop_id`, `user_id`, `reason`, and `alert_level`. It does not carry `trace_id`, `source_message_id`, `queue_message_id`, `session_id`, `content_length`, or `content_hash`.

## 2. headless 注入行为

Current `HEADLESS_MODE=1` behavior injects `DummyNotificationService`.

```text
HEADLESS_MODE=1
  -> configure_standard_services()
  -> register NotificationService = DummyNotificationService()
```

`DummyNotificationService.alert_human_fallback()` only logs the transfer request. It does not call PushPlus / clawbot.

Conclusion:

T084-A finding:

**Headless mode did not satisfy the confirmed product decision that transfer-to-human must trigger an external PushPlus clawbot notification.**

This is the main delivery gap found by T084-A. The code attempts to notify through the abstraction, but the headless implementation is a no-op logger.

T084-B status:

This gap has been addressed for the configured case. Headless mode now calls PushPlus / clawbot when `PUSHPLUS_ENABLED=true` and `PUSHPLUS_TOKEN` is present.

## 3. 转人工入口覆盖表

| Entry | Current trigger path | External PushPlus in desktop | External PushPlus in headless | Notes |
| --- | --- | --- | --- | --- |
| `image_intercept` | `AIReplyHandler` image branch | Yes, if PushPlus enabled and token configured | Yes, if PushPlus enabled and token configured | Metadata includes `action=image_intercept`, trace ids, content hash, reply hash. |
| `video_intercept` | `AIReplyHandler` video branch | Yes, if PushPlus enabled and token configured | Yes, if PushPlus enabled and token configured | Metadata includes `action=video_intercept`, trace ids, content hash, reply hash. |
| keyword `transfer_human` | `MessagePipeline._alert_transfer_human()` | Yes, if PushPlus enabled and token configured | Yes, if PushPlus enabled and token configured | Metadata includes `action=keyword_transfer_human`. |
| missing dataset | `MessagePipeline` dataset guard | Yes, if PushPlus enabled and token configured | Yes, if PushPlus enabled and token configured | Metadata includes `action=missing_fastgpt_dataset_id`. |
| FastGPT timeout / non-200 / failed | `MessagePipeline` fallback and repeated-failure paths | Yes, if PushPlus enabled and token configured | Yes, if PushPlus enabled and token configured | Metadata includes fallback action, trace ids, content hash, optional reply hash. |
| FastGPT empty reply | `AIReplyHandler` empty result path | Yes, if PushPlus enabled and token configured | Yes, if PushPlus enabled and token configured | Metadata includes `action=ai_empty_reply`. |
| unsafe reply | `AIReplyHandler._post_process_guardrail()` | Yes, if PushPlus enabled and token configured | Yes, if PushPlus enabled and token configured | Metadata includes `action=unsafe_reply` and reply hash/preview. |
| SendMessage failed | `AIReplyHandler._send_reply()` non-ok / exception paths | Yes, if PushPlus enabled and token configured | Yes, if PushPlus enabled and token configured | Metadata includes `final_status=reply_send_failed`. |
| SendMessage unknown delivery | `AIReplyHandler._send_reply()` unknown-delivery path | Yes, if PushPlus enabled and token configured | Yes, if PushPlus enabled and token configured | Metadata includes `final_status=reply_delivery_unknown`. |
| Auto-reply final reconnect failure | `AutoReplyManager._on_final_reconnect_failed()` | Yes, if PushPlus enabled and token configured | Not applicable to headless worker | UI manager path, not primary headless runtime. |

Coverage conclusion:

The main transfer entry points call the notification abstraction. After T084-B/T084-D, they can reach PushPlus in headless mode when PushPlus is enabled and configured, and they pass trace metadata where available.

## 4. 通知字段与脱敏检查

### 4.1 Fields currently available to notification service

Notification service receives only:

- `shop_id`
- `user_id`
- `reason`
- `alert_level`

`UINotificationService` then enriches the PushPlus body by querying session context.

### 4.2 Fields included in PushPlus body today

`HumanAlertContextBuilder` / `format_human_alert_message()` currently includes:

- shop name
- account name
- buyer ID
- session ID
- alert reason
- alert level
- session status
- timestamp
- latest buyer message preview
- latest assistant reply preview

### 4.3 Privacy finding

Current PushPlus body can include latest buyer message text and latest assistant reply text, truncated to 500 characters.

T084-B product decision allows these previews for transfer-to-human notifications only. The current rule is:

- PushPlus transfer alerts may include a latest-message preview.
- Each preview is limited to 500 characters.
- Credential-like values are redacted before sending.
- Ordinary logs, trace events, and diagnose packages must still avoid full buyer / AI text.

Residual risk remains because short messages can be fully present in the PushPlus alert by design. This is now a controlled product tradeoff, not a general logging allowance.

### 4.4 Missing diagnostic fields

T084-B/T084-D notification content includes or can include:

- `trace_id`
- `source_message_id`
- `queue_message_id`
- `customer_uid` / `from_uid` as a named trace field
- `content_length`
- `content_hash`
- `reply_length`
- `reply_hash`
- send outcome final status

The notification interface now accepts optional `metadata`. Old callers remain compatible.

Current recommended metadata fields:

- `trace_id`
- `source_message_id`
- `queue_message_id`
- `session_id`
- `shop_id`
- `user_id`
- `customer_uid`
- `action`
- `message_type`
- `content_length`
- `content_hash`
- `reply_length`
- `reply_hash`
- `final_status`

### 4.5 Token / cookie / authorization check

The audited notification formatting path does not intentionally include token, cookie, access token, or authorization values.

Residual risk:

- `PushPlusNotifier` logs raw provider response text up to 500 characters on non-200 / non-JSON / non-accepted responses.
- This is unlikely to include buyer content, but raw response logging should still be summarized in a later hardening patch.

## 5. 通知失败行为

Current behavior is mostly non-blocking:

- `UINotificationService` starts PushPlus delivery in a daemon thread.
- `_notify_pushplus()` catches exceptions and logs warnings.
- `PushPlusNotifier.send()` returns `PushPlusResult` and logs failure instead of raising for normal HTTP/API failures.
- `AIReplyHandler` and `MessagePipeline` notification call sites catch notification exceptions.

Conclusion:

Notification failure should not crash the consumer or block the main message handling path in the current desktop path.

Headless caveat:

Because headless mode uses `DummyNotificationService`, this non-blocking external delivery behavior is not exercised in production headless runtime.

## 6. 缺口和风险

### P0: headless external notification missing

Before T084-B, `HEADLESS_MODE=1` injected `DummyNotificationService`, so transfer-to-human did not reach PushPlus / clawbot.

Status:

- Fixed when PushPlus is enabled and token is configured.
- Still intentionally falls back to Dummy when PushPlus is disabled or token is missing.

### Controlled risk: notification body may include buyer / AI message preview

PushPlus body includes latest buyer and assistant message previews up to 500 characters.

Impact:

- Allowed only for PushPlus transfer alerts by product decision.
- Must not leak to ordinary logs, trace events, or diagnose packages.
- Credential-like values are redacted before sending.

### P1: trace fields do not reach notifications

`NotificationService.alert_human_fallback()` does not accept trace metadata.

Impact:

- Operators cannot reliably correlate PushPlus alert to `trace_id`, `queue_message_id`, send outcome, or message hash.
- Troubleshooting still requires manual DB/log correlation.

### P1: send failure reason may contain unsanitized exception text

`AIReplyHandler._send_reply()` sends manual-transfer reasons derived from send result summaries or exception strings.

Impact:

- Usually safe after T006/T005 redaction work, but exception strings should still be normalized to `error_type` and short summary.

### P2: raw PushPlus provider response logging

`PushPlusNotifier` logs raw response body snippets for failures.

Impact:

- Lower privacy risk than buyer content, but still inconsistent with the redaction policy.

## 7. 建议补丁任务

### T084-B: headless PushPlus notification service

Goal:

- Add a headless-safe notification implementation that calls PushPlus / clawbot without PyQt.
- Keep desktop `UINotificationService` unchanged.
- Preserve non-blocking behavior and failure isolation.

Acceptance:

- `HEADLESS_MODE=1` + `PUSHPLUS_ENABLED=true` + valid token calls PushPlus.
- Missing token or disabled PushPlus logs a clear warning/result and does not crash.
- Notification failure does not fail message processing.

### T084-C: notification content redaction

Goal:

- Replace latest buyer / assistant text previews in PushPlus body with summary fields.

Recommended fields:

- `trace_id`
- `shop_id`
- `user_id`
- `customer_uid`
- `session_id`
- `action`
- `reason`
- `content_length`
- `content_hash`
- `reply_length`
- `reply_hash`
- `message_type`
- `final_status`

Acceptance:

- PushPlus body contains no full buyer message or full AI reply.
- Existing operator context remains sufficient for triage.

### T084-D: notification trace metadata propagation

Goal:

- Extend notification call sites or payload model to carry trace metadata.
- Avoid overloading free-form `reason`.

Minimal option:

- Add optional `metadata: dict | None = None` to `NotificationService.alert_human_fallback()`.
- Keep old callers compatible.

### T084-E: PushPlus response log redaction

Goal:

- Stop logging raw provider response body.
- Log `status_code`, `error_type`, `response_length`, `response_hash`, and provider code/message when safe.

## 8. 建议 fake 测试项

### Headless DI notification test

Setup:

- `HEADLESS_MODE=1`
- `PUSHPLUS_ENABLED=true`
- fake PushPlus sender

Expected:

- `container.get("NotificationService").alert_human_fallback(...)` calls fake PushPlus sender.
- No PyQt import required.
- Failure does not raise to caller.

Current result expected before T084-B:

- Fails product expectation, because `DummyNotificationService` only logs.

### Desktop notification failure isolation test

Setup:

- `UINotificationService`
- fake notifier raises or returns failure

Expected:

- `alert_human_fallback()` returns without raising.
- Warning log is emitted.

### Notification redaction test

Setup:

- fake latest buyer message and assistant reply with recognizable text.

Expected after T084-C:

- PushPlus body contains `content_length/content_hash/reply_length/reply_hash`.
- PushPlus body does not contain the raw buyer or assistant text.

### Transfer entry coverage tests

Cases:

- image intercept
- video intercept
- keyword transfer_human
- missing dataset
- FastGPT failed/empty
- unsafe reply
- SendMessage failed
- unknown delivery

Expected:

- each path calls notification abstraction exactly once where product policy requires manual intervention
- no path logs or sends raw buyer content / full AI reply
- notification failures are isolated

### Trace metadata test

Setup:

- context with `trace_id`, `source_message_id`, `queue_message_id`, `session_id`, `content_length`, `content_hash`

Expected after T084-D:

- notification payload includes these fields
- PushPlus output includes trace fields
- no token/cookie/access token/authorization fields appear
