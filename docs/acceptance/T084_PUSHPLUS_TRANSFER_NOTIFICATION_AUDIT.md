# T084 PushPlus / Clawbot Transfer Notification Audit

Date: 2026-05-20

Scope: PushPlus / clawbot transfer-to-human notification chain, headless injection behavior, controlled notification context, trace metadata propagation, and log / diagnose redaction review.

## 1. Current Notification Chain

### 1.1 Desktop / PyQt path

Desktop runtime still injects `UINotificationService`.

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

### 1.2 Headless path

T084-A historical finding:

- `HEADLESS_MODE=1` previously injected `DummyNotificationService`.
- That meant transfer-to-human paths did not call PushPlus / clawbot in headless runtime.

Current status after T084-B:

- `HEADLESS_MODE=1` + `PUSHPLUS_ENABLED=true` + configured `PUSHPLUS_TOKEN` injects `HeadlessNotificationService`.
- `HeadlessNotificationService` does not depend on PyQt.
- It uses `PushPlusNotifier` to send clawbot notifications.
- If PushPlus is disabled or token is missing, headless mode falls back to `DummyNotificationService` and logs a clear warning.

### 1.3 Notification interface

`NotificationService.alert_human_fallback(...)` remains backward compatible:

```text
alert_human_fallback(
    shop_id=...,
    user_id=...,
    reason=...,
    alert_level=...,
    metadata=None
)
```

Old callers that do not pass `metadata` continue to work.

## 2. Transfer Entry Coverage

After T084-B and T084-D, the primary transfer-to-human paths can call the notification abstraction and pass trace metadata where available.

| Entry | Current trigger path | Headless PushPlus behavior | Metadata status |
| --- | --- | --- | --- |
| `image_intercept` | `AIReplyHandler` image branch | Sends PushPlus when enabled and token configured | Includes `action=image_intercept`, trace ids, content hash, reply hash |
| `video_intercept` | `AIReplyHandler` video branch | Sends PushPlus when enabled and token configured | Includes `action=video_intercept`, trace ids, content hash, reply hash |
| keyword `transfer_human` | `MessagePipeline._alert_transfer_human()` | Sends PushPlus when enabled and token configured | Includes `action=keyword_transfer_human` |
| missing dataset | `MessagePipeline` dataset guard | Sends PushPlus when enabled and token configured | Includes `action=missing_fastgpt_dataset_id` |
| FastGPT timeout / non-200 / failed | `MessagePipeline` fallback paths | Sends PushPlus when enabled and token configured | Includes fallback action, trace ids, content hash, optional reply hash |
| FastGPT empty reply | `AIReplyHandler` empty result path | Sends PushPlus when enabled and token configured | Includes `action=ai_empty_reply` |
| unsafe reply | `AIReplyHandler._post_process_guardrail()` | Sends PushPlus when enabled and token configured | Includes `action=unsafe_reply` and reply hash / preview |
| SendMessage failed | `AIReplyHandler._send_reply()` non-ok / exception paths | Sends PushPlus when enabled and token configured | Includes `final_status=reply_send_failed` |
| SendMessage unknown delivery | `AIReplyHandler._send_reply()` unknown-delivery path | Sends PushPlus when enabled and token configured | Includes `final_status=reply_delivery_unknown` |

Metadata fields propagated by T084-D include:

- `trace_id`
- `source_message_id`
- `queue_message_id`
- `session_id`
- `shop_id`
- `user_id`
- `customer_uid` / `from_uid`
- `action`
- `reason`
- `message_type`
- `content_length`
- `content_hash`
- `reply_length`
- `reply_hash`
- `final_status`

## 3. Controlled Notification Context

Product decision:

- PushPlus / clawbot transfer-to-human notifications may include recent buyer / seller / AI text previews.
- This is a business notification exception needed for human customer-service triage.
- The allowance applies only to PushPlus transfer alerts.
- Ordinary logs, trace events, status files, and diagnose packages must still avoid full buyer messages and full AI replies.

Preview policy:

- `buyer_message_preview` is limited to 500 characters.
- `seller_or_ai_reply_preview` is limited to 500 characters.
- Only the latest relevant turn is used; full conversation history is not concatenated.
- Empty values are safe.
- Truncated previews are marked with truncation metadata.

Credential redaction applies before sending notification content. The following credential-like values are masked:

- `token`
- `cookie`
- `access_token`
- `authorization`
- `api_key`
- `secret`
- `Bearer ...`
- `ark-...`
- `fastgpt-...`

## 4. PushPlus Success Semantics

System-side success is defined as:

- PushPlus API response accepted by provider.
- `provider_code=200` / response accepted is treated as notification send success by this system.

This does not prove:

- the human operator has read the notification,
- the client app has displayed it,
- the clawbot delivery endpoint has a separate read receipt.

If strict delivery / read confirmation is required, a future receipt mechanism is needed.

T084-B.1 real smoke status:

- Headless PushPlus smoke used synthetic `shop_id`, `user_id`, `reason`, and metadata.
- No real buyer message was used.
- PushPlus API returned accepted provider status.
- System treated the notification as sent.
- Logs did not print preview text or credentials.

## 5. Log And Diagnose Redaction Review

T084-E read-only review conclusion:

- Ordinary logs do not output `buyer_message_preview`.
- Ordinary logs do not output `seller_or_ai_reply_preview`.
- PushPlus provider raw response body is not logged.
- PushPlus response logs record `status_code`, `provider_code`, `response_length`, and `response_hash`.
- Diagnose scripts do not actively package PushPlus notification body content.
- Diagnose scripts redact common credential keys from copied status / log artifacts.

Known limitation:

- Credential filtering is best-effort regex redaction, not a full DLP system.
- If future code writes notification body text into normal logs, diagnose log excerpts may include non-credential business text unless that future path also redacts it.

## 6. Notification Failure Behavior

Notification failure is isolated from message processing:

- `HeadlessNotificationService` catches notifier exceptions.
- `PushPlusNotifier.send()` returns structured failure results for HTTP/API failures.
- Notification call sites in `AIReplyHandler` and `MessagePipeline` catch notification exceptions.
- Failures are logged with status, length/hash, trace id, and error type where available.
- Failures do not raise back into the consumer path.

## 7. Remaining Risks

### Controlled privacy risk: notification preview content

Short buyer / seller / AI messages may be fully present in the PushPlus alert because the preview limit is 500 characters. This is an accepted product tradeoff for transfer-to-human handling, not a general logging allowance.

### Operational risk: PushPlus accepted is not read confirmation

`provider_code=200` means the provider accepted the request. It does not confirm human read / display. Future work is required if the business needs delivery receipts.

### Redaction risk: best-effort pattern matching

Credential redaction covers common keys and token patterns but cannot guarantee removal of every possible secret format.

## 8. Suggested Follow-Up Tests

Recommended future hardening:

- Explicit test that PushPlus provider raw response body is not emitted to logs.
- Real smoke test in production-like headless environment after any PushPlus config change.
- Regression test that diagnose packages do not contain `.env`, PushPlus token, cookies, or notification preview body.
