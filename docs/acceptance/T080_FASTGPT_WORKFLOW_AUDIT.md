# T080 FastGPT Workflow Business Acceptance Audit

Date: 2026-05-20

Scope: read-only audit of the current PDD message handling, MessagePipeline, FastGPT integration, manual-transfer behavior, fallback behavior, and observability. This report does not change code, FastGPT configuration, prompts, `.env`, or business logic.

## 1. 当前 FastGPT 调用链路

当前用户消息链路为：

1. `PDDChannel` WebSocket message loop receives a raw PDD message.
2. `Channel/pinduoduo/core/pdd_message_handler.py` parses JSON, builds `PDDChatMessage`, then converts it to `Context`.
3. The handler writes trace metadata into `Context.kwargs`: `trace_id`, `source_message_id`, `queue_name`, `message_type`, `content_length`, and `content_hash`.
4. Queueable messages are put into `Message` queue `pdd_{shop_id}`.
5. `MessageConsumer` dequeues `MessageWrapper`, builds metadata, selects `AIReplyHandler`, and passes `Context + metadata`.
6. `AIReplyHandler.handle()` applies hard intercepts and locks, then calls `_get_ai_reply()`.
7. `_get_ai_reply()` lazily creates `MessagePipeline` with `DatabaseManager`, `SessionManager`, `KeywordHandler`, and `FastGPTHandler`.
8. `MessagePipeline.process()` resolves shop, conversation, keyword rules, dataset_id, and builds FastGPT messages.
9. `FastGPTHandler.call()` sends a blocking HTTP POST to `{FASTGPT_BASE_URL}/v1/chat/completions` through `asyncio.to_thread`.
10. Pipeline returns `reply`, `transfer_human`, or `skip`; `AIReplyHandler._send_reply()` calls PDD `SendMessage.send_text()`.

Important implementation points:

- `FASTGPT_BASE_URL` is read through `core/settings.py`.
- FastGPT API key is read from `AppConfig` key `fastgpt:api_key`; `app.py` can seed this from `FASTGPT_API_KEY` when no DB value exists.
- Dataset ID is read from `shops.fastgpt_dataset_id`.
- `chat_id` is generated as `{shop_platform_id}_{buyer_id}_{session_id}`.
- No active runtime use of `FASTGPT_APP_ID` was found in the current message pipeline; it is documented as reserved configuration.
- Every shop expected to auto-reply through FastGPT must have `shops.fastgpt_dataset_id` configured. Missing dataset id triggers the transfer-to-human path instead of a FastGPT request.

## 2. 当前 MessagePipeline 决策流程

The effective decision order is:

1. WebSocket/system filtering:
   - System/auth/withdraw/mall_cs/transfer messages are handled immediately or skipped.
   - Customer service messages from `mall_cs` renew the human lock heartbeat and are not queued.
2. `AIReplyHandler` pre-pipeline hard intercepts:
   - Image content triggers manual-transfer alert and sends `IMAGE_INTERCEPT_REPLY`.
   - Video content triggers manual-transfer alert and sends a fixed video-received reply.
   - Emotion content sends a lightweight default reply without manual transfer.
   - Empty content is skipped silently.
   - Unsupported message types are skipped with `action=unsupported_message_type`.
   - Redis-compatible `human_lock` check can skip AI processing.
   - SQLite-backed static rules through `redis_manager.get_static_rules(shop_id)` can send a fixed reply.
   - Inference lock prevents concurrent AI calls for the same session.
3. `MessagePipeline` session routing:
   - Missing `buyer_id` or content: `skip`.
   - Missing shop: `skip`.
   - `pending_human` / `human_handling`: skip, except a second fallback reminder may be sent while pending.
4. `KeywordHandler` local keyword routing:
   - `auto_reply`: returns a fixed reply.
   - `transfer_human`: sets `pending_human`, alerts human service, returns transfer reply.
   - `block`: returns `action=block`.
5. FastGPT route:
   - Missing `fastgpt_dataset_id`: set `pending_human`, alert human service, return transfer reply.
   - Successful FastGPT content: trim to 200 chars, store assistant message, return reply unless the reply contains transfer intent.
   - FastGPT failure or empty content: set `pending_human`, send first/second fallback when allowed, otherwise skip and wait for human service.
6. Send result:
   - PDD explicit ok: `final_status=reply_sent`.
   - PDD non-ok / `None` / exception: `final_status=reply_send_failed`.
   - Send call succeeds but delivery is not explicit ok: `final_status=reply_delivery_unknown`.

Audit note: `KeywordHandler` can return `action=block`, but `AIReplyHandler._get_ai_reply()` currently only maps `reply`, `transfer_human`, and `skip`. `block` falls through to the legacy bot/empty reply path. This should be covered by T081/T085 acceptance tests before production business sign-off.

## 3. 当前知识库依赖

Current FastGPT knowledge dependency is dataset-based:

- Shop table field: `shops.fastgpt_dataset_id`.
- UI entry: `ui/Knowledge_ui.py` dataset field.
- Runtime route: `MessagePipeline.process()` reads `shop["fastgpt_dataset_id"]`.
- FastGPT request payload includes `datasetId` and `chatId`.

The codebase also contains local SQLite knowledge tables:

- `product_knowledge`
- `customer_service_knowledge`

However, the audited FastGPT runtime path does not directly query these tables for retrieval before calling FastGPT. Instead, it relies on the configured FastGPT dataset. `SessionManager.build_context_messages()` has a `cached_products` parameter, but the current pipeline uses an in-memory `_product_cache` and no audited path populates it as a reliable business retrieval source.

Acceptance implication: FastGPT dataset quality is now the primary business knowledge dependency. Every shop that should answer automatically must have a valid `fastgpt_dataset_id` and a populated FastGPT dataset.

## 4. 当前转人工策略

Manual-transfer triggers found in the current flow:

- Image message intercept in `AIReplyHandler`.
- Redis-compatible human lock says the session is locked.
- Conversation status is `pending_human` or `human_handling`.
- Keyword action is `transfer_human`.
- Missing FastGPT dataset ID.
- FastGPT reply contains transfer intent keywords such as “转人工”.
- FastGPT repeated failures reach the configured hard-transfer threshold.
- Pipeline exception.
- SendMessage failure or unknown delivery triggers manual-transfer alert.
- Post-process guardrail detects dangerous reply content and replaces it with safety fallback while alerting human service.

Important semantic detail:

- Headless mode injects `DummyNotificationService`; it logs manual-transfer alerts but does not push a UI notification.
- Desktop mode uses UI notification integration and may also call PushPlus depending on configuration.
- The current Redis manager is a compatibility layer backed by SQLite for static rules, but its human lock and inference lock methods are fail-open stubs. Durable manual state is mainly `Conversation.status`.

## 5. 当前兜底策略

There are multiple fallback layers:

- Image fallback: fixed `IMAGE_INTERCEPT_REPLY`.
- AIReplyHandler fallback pool: random `FALLBACK_REPLY_POOL`, then sets human lock.
- MessagePipeline fallback:
  - FastGPT failure sets conversation status to `pending_human`.
  - First fallback can be sent immediately.
  - Second reminder can be sent near pending-human expiry.
  - Further fallback is throttled and the message is skipped.
- FastGPTHandler failure counter:
  - Tracks session failures in memory.
  - After threshold, uses `TRANSFER_HUMAN_REPLY`.
- Safety guardrail fallback:
  - Dangerous generated replies are replaced by `SAFETY_FALLBACK`.

Risk: fallback state is split across `AIReplyHandler` in-memory state, `SessionManager` persisted fallback state, and `FastGPTHandler` in-memory failure counters. This makes business acceptance sensitive to process restarts and to which layer generated the fallback.

## 6. 当前日志与 trace 可观测性

Current trace chain is mostly complete:

- `pdd.message.received`
- `pdd.context.created`
- `pdd.message.queued`
- `pdd.consumer.dequeued`
- `pdd.handler.selected`
- `pdd.pipeline.started`
- `pdd.ai.request.started`
- `pdd.ai.request.succeeded`
- `pdd.ai.request.failed`
- `pdd.reply.send.started`
- `pdd.reply.send.succeeded`
- `pdd.reply.send.failed`
- `pdd.reply.send.call_succeeded status=unknown_delivery`
- `pdd.message.completed final_status=...`
- `pdd.message.skipped`
- `pdd.transfer_human.triggered`

The trace fields include `trace_id`, `source_message_id`, `queue_message_id`, `session_id`, `shop_id`, `user_id`, `customer_uid`, content length/hash, reply length/hash, send request ID, and PDD send summary.

Known observability gaps:

- `pdd.message.completed` currently only proves final send outcome when `_send_reply()` is reached. Pipeline completion is logged separately and should not be interpreted as delivery success.
- `KeywordHandler` logs the matched keyword in plain text. This is useful operationally but should be reviewed against privacy policy for sensitive buyer wording.
- `AIReplyHandler._match_static_reply()` still logs normalized content and reply preview in legacy diagnostic messages. That is a privacy debt and should be handled in a future privacy hardening task, not as part of this read-only audit.
- FastGPT request logs include `dataset_id` and `chat_id`. These are not API secrets, but they can still be operationally sensitive.

## 7. 当前业务风险

High priority risks:

1. Keyword `block` action may not be mapped by `AIReplyHandler._get_ai_reply()` and can fall into fallback behavior instead of deterministic silence.
2. FastGPT dataset ID is mandatory for automatic FastGPT replies; missing dataset immediately transfers to human.
3. Local SQLite product/customer-service knowledge tables are not clearly part of the live FastGPT retrieval path.
4. Human lock semantics are split: Redis-compatible stubs are fail-open, while actual long-lived manual state is `Conversation.status`.
5. `MessagePipeline` and `AIReplyHandler` both have fallback state; restart behavior and duplicate fallback behavior need test coverage.

Medium priority risks:

1. Static rule sources are split between `redis_manager.get_static_rules()` and `KeywordHandler` DB keywords.
2. Generated replies are truncated to 200 characters after FastGPT returns. This avoids long replies but can cut structured answers unexpectedly.
3. FastGPT timeout is 25 seconds with one retry; under outage this can delay a session before fallback.
4. Headless manual-transfer alert is currently log-only unless external notification is separately configured.
5. PushPlus logs and response handling should be checked during business acceptance if PushPlus is part of delivery.

Low priority risks:

1. `FASTGPT_APP_ID` is reserved only and is not used in the current runtime path. Do not treat it as required deployment configuration until the workflow explicitly adopts it.
2. Conversation compression uses a separate LLM endpoint and may log raw response snippets on failure in existing code; this should be reviewed if compression is enabled in production.
3. `mall_cs` heartbeat renews compatibility human lock, but with current fail-open Redis compatibility this may not have durable effect beyond logs.

## 8. 必须补齐的客服场景

Business acceptance should cover at least these categories:

- Greeting and short utterances: “在吗”, “你好”, “有人吗”.
- Product basic questions: price, size, scent, ingredients, usage, shelf life.
- Product-specific questions with goods card/spec/order context.
- Logistics: shipment time, express provider, arrival estimate, delayed delivery.
- Promotions: discount, coupons, gifts, member price.
- After-sales: refund, exchange, damaged item, wrong item, missing item.
- Complaint/redline: bad review, 12315, media exposure, compensation, fake product.
- Human service request: explicit “转人工/人工客服/找商家”.
- Image/video/emotion messages.
- Empty and unsupported message types.
- Ambiguous buyer messages and repeated short follow-ups.
- Missing dataset ID.
- FastGPT timeout/non-200/empty content.
- PDD send explicit ok, non-ok, exception, and unknown delivery.
- Pending-human second reminder and fallback throttling.
- Session restart behavior after worker restart.

## 9. 建议验收测试集分类

Suggested T081 test matrix:

| Category | Goal | Expected outcome |
| --- | --- | --- |
| Basic greeting | Confirm normal reply route | `reply_sent` or configured static reply |
| Product FAQ | Validate FastGPT dataset retrieval | Accurate reply grounded in dataset |
| Logistics | Validate policy answer | Reply only if policy exists, otherwise safe fallback/transfer |
| Promotion | Avoid invented discounts | No unsupported promise |
| Refund/complaint | Confirm human transfer | `transfer_human` and manual alert |
| Image | Confirm hard intercept | Image fixed reply and transfer alert |
| Missing dataset | Confirm fail-safe | Transfer reply, no FastGPT request success |
| FastGPT timeout | Confirm fallback | Pending human + fallback or skip by throttle |
| Send failure | Confirm final status | `reply_send_failed` and manual alert |
| Unknown delivery | Confirm final status | `reply_delivery_unknown`, not `reply_sent` |
| Human state | Confirm AI silence | `message.skipped` while pending/human |
| Keyword block | Confirm intended behavior | Must be specified and tested |

## 10. 后续任务建议

T081 客服场景测试集:

- Build a deterministic scenario matrix for greeting, product FAQ, logistics, refund, complaint, image, missing dataset, FastGPT failure, send failure, and human lock.
- Include expected event names and final statuses.

T082 workflow 节点补强:

- Decide whether static rules, keyword rules, FastGPT workflow, or code should own each business decision.
- Clarify `block` action behavior.
- Clarify whether app_id should be used or removed from delivery docs.

T083 知识库质量验收:

- Verify each production shop has `fastgpt_dataset_id`.
- Sample FastGPT dataset coverage for product, logistics, refund, and after-sales policies.
- Define minimum answer accuracy and no-invention criteria.

T084 转人工策略验收:

- Validate transfer triggers, notification path, PushPlus behavior, and headless log-only behavior.
- Define manual reset rules for `pending_human` and human handling.

T085 AI 回复回归测试:

- Create fake FastGPT and fake SendMessage tests for all pipeline outcomes.
- Assert trace event sequence and final status semantics.
- Include restart/fallback throttling cases.
