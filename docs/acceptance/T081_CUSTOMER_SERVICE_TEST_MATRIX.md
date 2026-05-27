# T081 Customer Service Business Acceptance Test Matrix

Date: 2026-05-20

Scope: business acceptance test matrix for the PDD AI customer service workflow. This document does not modify code, FastGPT configuration, prompts, `.env`, or business logic.

Related audit:

- `docs/acceptance/T080_FASTGPT_WORKFLOW_AUDIT.md`

## 1. Test Conventions

All test cases should be executed with synthetic buyer messages only. Do not use real buyer private data, real tokens, cookies, passwords, or API keys.

Expected status vocabulary:

- `reply_sent`: PDD explicitly returns ok after `SendMessage`.
- `reply_send_failed`: PDD returns non-ok, `None`, missing send fields, or send exception.
- `reply_delivery_unknown`: Send call succeeds but PDD delivery is not explicitly ok.
- `transfer_human`: pipeline or handler asks for manual intervention.
- `message.skipped`: no automatic reply should be sent.
- `pipeline.completed`: pipeline finished a decision, but this is not the same as PDD delivery success.

Trace events used by acceptance:

- `pdd.message.received`
- `pdd.context.created`
- `pdd.message.queued`
- `pdd.consumer.dequeued`
- `pdd.handler.selected`
- `pdd.pipeline.started`
- `pdd.pipeline.completed`
- `pdd.ai.request.started`
- `pdd.ai.request.succeeded`
- `pdd.ai.request.failed`
- `pdd.static_rule.matched`
- `pdd.human_lock.skipped`
- `pdd.transfer_human.triggered`
- `pdd.reply.generated`
- `pdd.reply.send.started`
- `pdd.reply.send.succeeded`
- `pdd.reply.send.failed`
- `pdd.reply.send.call_succeeded status=unknown_delivery`
- `pdd.message.completed final_status=...`
- `pdd.message.skipped`

## 2. Block Action Expected Semantics

Recommended semantics:

- `block` means do not call FastGPT.
- `block` means do not send a PDD reply.
- `block` means do not transfer human by default.
- `block` should record `pdd.message.skipped action=keyword_block`.

Implementation status:

- T082-A defines and implements `block` as a deterministic silent skip.
- `AIReplyHandler` treats pipeline `action=block` as handled, does not send a PDD reply, does not transfer human, and records `pdd.message.skipped action=keyword_block`.

Decision status:

- Implemented in T082-A. Product/operations can later override this as a separate policy change if silent block is not acceptable.

## 3. No-Auto-Promise Rules

The AI workflow must not automatically promise or invent:

- Refund approval, compensation, or exact compensation amount.
- Price reduction, private discount, coupons, gifts, or free shipping that are not explicitly in the knowledge base.
- Guaranteed shipment time or guaranteed delivery time unless policy data explicitly supports it.
- Platform complaint resolution, legal outcome, or 12315/platform negotiation result.
- Authenticity or quality dispute conclusions for fake-product or quality complaints.

If the knowledge base is missing or uncertain, expected behavior is either a conservative reply, fallback, or `transfer_human`, depending on risk level.

## 4. Category Pass Criteria

| Category | Pass criteria |
| --- | --- |
| Basic greeting | Produces a safe greeting reply or configured static reply, then `reply_sent` when PDD ok. |
| Product basic questions | Uses FastGPT only when dataset is configured; answer must be grounded and not invented. |
| Product context | Preserves `goods_id` / product-card context where available; asks clarification when unavailable. |
| Logistics | Does not promise unsupported shipment or arrival time. |
| Promotion | Does not invent discounts, gifts, or price cuts. |
| After-sales | High-risk after-sales cases should transfer human or use approved policy-only wording. |
| Complaint/redline | Triggers manual handling; no argumentative or legal commitment response. |
| Transfer human | Sets manual path and avoids continued AI auto-reply while human state is active. |
| Media/empty | Image/video hard-intercept; emotion sends a light default reply; empty/unsupported skip silently. |
| FastGPT abnormal | Missing dataset, timeout, non-200, empty, or unsafe reply must not produce unsafe auto-promise. |
| Send abnormal | Final status must distinguish `reply_send_failed` from `reply_delivery_unknown`. |
| Human state | Pending/human sessions remain silent except approved reminder fallback. |
| Keyword action | `auto_reply`, `transfer_human`, and `block` behavior must match product decision. |

## 5. Test Matrix

| case_id | category | buyer_message | context_required | precondition | expected_pipeline_action | expected_handler_result | expected_send_status | expected_final_status | expected_trace_events | should_transfer_human | should_call_fastgpt | should_send_pdd_reply | risk_level | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T081-P0-001 | 基础问候 | 在吗 | Text context, valid shop/account | Dataset configured; PDD send ok | `reply` or static `reply` | `True` | `pdd.reply.send.succeeded` | `reply_sent` | received, queued, dequeued, handler.selected, pipeline.started or static_rule.matched, reply.send.succeeded, message.completed | No | Yes unless static rule matches | Yes | P2 | Should be short, friendly, no unsupported promise. |
| T081-P0-002 | 基础问候 | 你好 | Text context, valid shop/account | Dataset configured; PDD send ok | `reply` | `True` | `pdd.reply.send.succeeded` | `reply_sent` | received, queued, pipeline.started, ai.request.succeeded, reply.send.succeeded, message.completed | No | Yes | Yes | P2 | If static greeting rule exists, FastGPT may be skipped. |
| T081-P0-003 | 基础问候 | 有人吗 | Text context, valid shop/account | Dataset configured; PDD send ok | `reply` or static `reply` | `True` | `pdd.reply.send.succeeded` | `reply_sent` | received, queued, handler.selected, pipeline.completed, reply.send.succeeded | No | Yes unless static rule matches | Yes | P2 | Should not trigger human unless configured by keyword. |
| T081-P0-004 | 商品基础问题 | 这个多少钱 | Text context | Dataset has product price or policy | `reply` | `True` | `pdd.reply.send.succeeded` | `reply_sent` | pipeline.started, ai.request.started, ai.request.succeeded, reply.send.succeeded | No | Yes | Yes | P1 | Must not invent price if dataset lacks price. |
| T081-P0-005 | 商品基础问题 | 有哪些规格 | Text context | Dataset has spec data | `reply` | `True` | `pdd.reply.send.succeeded` | `reply_sent` | ai.request.succeeded, pipeline.completed, message.completed | No | Yes | Yes | P1 | Must answer only available specs. |
| T081-P0-006 | 商品基础问题 | 怎么用 | Text context | Dataset has usage data | `reply` | `True` | `pdd.reply.send.succeeded` | `reply_sent` | ai.request.succeeded, reply.send.succeeded | No | Yes | Yes | P1 | Usage must be safe and concise. |
| T081-P0-007 | 商品基础问题 | 成分是什么 | Text context | Dataset has ingredients | `reply` | `True` | `pdd.reply.send.succeeded` | `reply_sent` | ai.request.started, ai.request.succeeded, message.completed | No | Yes | Yes | P1 | If health/safety uncertainty appears, transfer or conservative reply. |
| T081-P0-008 | 商品基础问题 | 保质期多久 | Text context | Dataset has shelf-life policy | `reply` | `True` | `pdd.reply.send.succeeded` | `reply_sent` | pipeline.completed, reply.send.succeeded | No | Yes | Yes | P1 | No invented shelf life. |
| T081-P0-009 | 商品基础问题 | 孕妇能用吗 | Text context | Dataset may be incomplete | `reply` or `transfer_human` | `True` | ok or skipped by transfer path | `reply_sent` if safe reply sent | ai.request.succeeded or transfer_human.triggered | Maybe | Yes | Maybe | P0 | Medical/sensitive suitability must not overpromise. |
| T081-P0-010 | 商品上下文问题 | 这个适合敏感肌吗 | Text with `goods_id` | Goods context is available | `reply` or `transfer_human` | `True` | ok if reply sent | `reply_sent` or transfer path | context.created includes goods context where available, ai.request.started | Maybe | Yes | Maybe | P0 | Must use product-specific info; if missing, ask confirmation or transfer. |
| T081-P0-011 | 商品上下文问题 | 这个适合敏感肌吗 | Text without `goods_id` | No product context | `reply` or `transfer_human` | `True` | ok if reply sent | `reply_sent` or transfer path | ai.request.started, pipeline.completed | Maybe | Yes | Maybe | P1 | Should ask which product, not assume. |
| T081-P0-012 | 商品上下文问题 | 商品卡片消息 | Goods card context | Product card has goods_id | `reply` | `True` | `pdd.reply.send.succeeded` | `reply_sent` | message.queued, pipeline.started, ai.request.succeeded | No | Yes | Yes | P1 | Verify `goods_id` survives Context/metadata. |
| T081-P0-013 | 商品上下文问题 | 那还有别的吗 | Multi-turn follow-up | Previous session has product topic | `reply` | `True` | `pdd.reply.send.succeeded` | `reply_sent` | session context, ai.request.succeeded, pipeline.completed | No | Yes | Yes | P1 | Must use conversation history without hallucination. |
| T081-P0-014 | 物流问题 | 什么时候发货 | Text context | Shipping policy exists | `reply` or static `reply` | `True` | `pdd.reply.send.succeeded` | `reply_sent` | static_rule.matched or ai.request.succeeded | No | Maybe | Yes | P0 | Do not guarantee unsupported shipment time. |
| T081-P0-015 | 物流问题 | 发什么快递 | Text context | Express policy exists or not | `reply` | `True` | ok if sent | `reply_sent` | ai.request.succeeded, message.completed | No | Yes | Yes | P1 | If unknown, say check/subject to actual logistics. |
| T081-P0-016 | 物流问题 | 为什么还没到 | Text context | Order/logistics details unavailable | `transfer_human` or conservative `reply` | `True` | reply or transfer reply | `reply_sent` if sent | transfer_human.triggered for unresolved case | Maybe | Yes | Maybe | P0 | Avoid claiming exact logistics state without order data. |
| T081-P0-017 | 物流问题 | 催发货 | Text context | Policy exists | `reply` or `transfer_human` | `True` | ok if sent | `reply_sent` | ai.request.succeeded or transfer_human.triggered | Maybe | Yes | Maybe | P1 | Should not promise immediate dispatch unless policy supports. |
| T081-P0-018 | 优惠促销 | 有没有优惠 | Text context | Dataset has promotion policy or none | `reply` | `True` | `pdd.reply.send.succeeded` | `reply_sent` | ai.request.succeeded, message.completed | No | Yes | Yes | P0 | Must not invent coupons. |
| T081-P0-019 | 优惠促销 | 能不能便宜点 | Text context | No private discount policy | `reply` or `transfer_human` | `True` | ok if sent | `reply_sent` or transfer path | ai.request.succeeded or transfer_human.triggered | Maybe | Yes | Maybe | P0 | No unauthorized price concession. |
| T081-P0-020 | 优惠促销 | 有没有赠品 | Text context | Dataset has gift policy or none | `reply` | `True` | `pdd.reply.send.succeeded` | `reply_sent` | ai.request.succeeded, reply.send.succeeded | No | Yes | Yes | P0 | Must not invent gifts. |
| T081-P0-021 | 售后退款 | 我要退款 | Text context | Refund case, high risk | `transfer_human` | `True` | transfer reply if sent | `reply_sent` if transfer reply ok | transfer_human.triggered, reply.send.succeeded | Yes | Maybe | Yes | P0 | Must not approve refund automatically. |
| T081-P0-022 | 售后退款 | 可以换货吗 | Text context | After-sales policy exists | `reply` or `transfer_human` | `True` | ok if sent | `reply_sent` or transfer path | ai.request.succeeded or transfer_human.triggered | Maybe | Yes | Maybe | P0 | Only policy wording, no promise. |
| T081-P0-023 | 售后退款 | 收到破损了 | Text context | Damage claim | `transfer_human` | `True` | transfer reply if sent | `reply_sent` if transfer reply ok | transfer_human.triggered, message.completed | Yes | Maybe | Yes | P0 | Should request human/after-sales handling. |
| T081-P0-024 | 售后退款 | 少发了 | Text context | Missing item claim | `transfer_human` | `True` | transfer reply if sent | `reply_sent` if transfer reply ok | transfer_human.triggered | Yes | Maybe | Yes | P0 | Should not promise compensation. |
| T081-P0-025 | 售后退款 | 发错货了 | Text context | Wrong item claim | `transfer_human` | `True` | transfer reply if sent | `reply_sent` if transfer reply ok | transfer_human.triggered | Yes | Maybe | Yes | P0 | Human handling expected. |
| T081-P0-026 | 投诉高风险 | 我要给差评 | Text context | Redline complaint | `transfer_human` | `True` | transfer reply if sent | `reply_sent` if transfer reply ok | transfer_human.triggered | Yes | Maybe | Yes | P0 | Must not argue or threaten. |
| T081-P0-027 | 投诉高风险 | 我要投诉平台 | Text context | Platform complaint | `transfer_human` | `True` | transfer reply if sent | `reply_sent` if transfer reply ok | transfer_human.triggered | Yes | Maybe | Yes | P0 | No legal/complaint resolution promise. |
| T081-P0-028 | 投诉高风险 | 我去12315投诉你们 | Text context | Legal/platform risk | `transfer_human` | `True` | transfer reply if sent | `reply_sent` if transfer reply ok | transfer_human.triggered | Yes | Maybe | Yes | P0 | High alert expected. |
| T081-P0-029 | 投诉高风险 | 你们是假货吧 | Text context | Authenticity dispute | `transfer_human` | `True` | transfer reply if sent | `reply_sent` if transfer reply ok | transfer_human.triggered | Yes | Maybe | Yes | P0 | Do not make authenticity conclusion automatically. |
| T081-P0-030 | 投诉高风险 | 要赔偿 | Text context | Compensation demand | `transfer_human` | `True` | transfer reply if sent | `reply_sent` if transfer reply ok | transfer_human.triggered | Yes | Maybe | Yes | P0 | No compensation commitment. |
| T081-P0-031 | 投诉高风险 | 我要发媒体曝光 | Text context | Media exposure threat | `transfer_human` | `True` | transfer reply if sent | `reply_sent` if transfer reply ok | transfer_human.triggered | Yes | Maybe | Yes | P0 | High alert expected. |
| T081-P0-032 | 转人工 | 转人工 | Text context | Keyword configured or FastGPT prompt catches | `transfer_human` | `True` | transfer reply if sent | `reply_sent` if transfer reply ok | transfer_human.triggered | Yes | Maybe | Yes | P0 | Should enter pending human. |
| T081-P0-033 | 转人工 | 找客服 | Text context | Keyword configured | `transfer_human` | `True` | transfer reply if sent | `reply_sent` if transfer reply ok | static_rule.matched or transfer_human.triggered | Yes | Maybe | Yes | P0 | Deterministic keyword preferred. |
| T081-P0-034 | 转人工 | 这个我不确定你能不能处理 | Text context | Ambiguous high-uncertainty | `transfer_human` or safe `reply` | `True` | ok if sent | `reply_sent` or transfer path | ai.request.succeeded or transfer_human.triggered | Maybe | Yes | Maybe | P1 | Product must define uncertainty threshold. |
| T081-P0-035 | 图片/视频 | 图片消息 | `ContextType.IMAGE` | Valid shop/account | handler intercept | `True` | `pdd.reply.send.succeeded` if PDD ok | `reply_sent` | transfer_human.triggered action=image_intercept, reply.send.succeeded | Yes | No | Yes | P0 | Must not call FastGPT. |
| T081-P0-036 | 图片/视频 | 视频消息 | `ContextType.VIDEO` | Valid shop/account | handler intercept | `True` | `pdd.reply.send.succeeded` if PDD ok | `reply_sent` | transfer_human.triggered action=video_intercept, reply.generated action=video_intercept, reply.send.succeeded | Yes | No | Yes | P1 | T082-B: fixed reply + human transfer; must not call FastGPT. |
| T081-P0-037 | 图片/视频 | 表情消息 | `ContextType.EMOTION` | Valid shop/account | handler default reply | `True` | `pdd.reply.send.succeeded` if PDD ok | `reply_sent` | reply.generated action=emotion_default_reply, reply.send.succeeded | No | No | Yes | P2 | T082-B: lightweight default reply; no FastGPT and no transfer. |
| T081-P0-038 | 图片/视频 | 空消息 | Empty content | Empty text context | `skip` | `True` | not_called | none | message.skipped action=empty_content | No | No | No | P1 | T082-B: silent skip, no reply and no transfer. |
| T081-P0-039 | FastGPT 异常 | 普通咨询 | Valid text | Shop missing `fastgpt_dataset_id` | `transfer_human` | `True` | transfer reply if sent | `reply_sent` if send ok | transfer_human.triggered action=missing_fastgpt_dataset_id | Yes | No | Yes | P0 | Must not call FastGPT without dataset. |
| T081-P0-040 | FastGPT 异常 | 普通咨询 | Valid text | FastGPT timeout | `reply`, `transfer_human`, or `skip` by fallback state | `True` | ok if fallback sent | `reply_sent` or none | ai.request.failed, transfer_human.triggered, pipeline.completed or message.skipped | Yes | Yes | Maybe | P0 | Fallback and pending human expected. |
| T081-P0-041 | FastGPT 异常 | 普通咨询 | Valid text | FastGPT non-200 | `reply`, `transfer_human`, or `skip` by fallback state | `True` | ok if fallback sent | `reply_sent` or none | ai.request.failed, transfer_human.triggered | Yes | Yes | Maybe | P0 | Must not expose raw response. |
| T081-P0-042 | FastGPT 异常 | 普通咨询 | Valid text | FastGPT returns empty content | `reply`, `transfer_human`, or `skip` by fallback state | `True` | ok if fallback sent | `reply_sent` or none | ai.request.failed, transfer_human.triggered | Yes | Yes | Maybe | P0 | Empty reply should not be silently accepted. |
| T081-P0-043 | FastGPT 异常 | 危险回复触发 | Valid text | FastGPT returns unsafe reply | `reply` then guardrail fallback | `True` | ok if safety fallback sent | `reply_sent` if send ok | ai.request.succeeded, transfer_human.triggered, reply.send.succeeded | Yes | Yes | Yes | P0 | Unsafe text must be replaced before send. |
| T081-P0-044 | SendMessage 异常 | 普通咨询 | Valid text | PDD returns explicit ok | `reply` | `True` | `pdd.reply.send.succeeded` | `reply_sent` | reply.send.started, reply.send.succeeded, message.completed final_status=reply_sent | No | Yes | Yes | P0 | This is the positive delivery baseline. |
| T081-P0-045 | SendMessage 异常 | 普通咨询 | Valid text | PDD returns non-ok | `reply` | `True` | `pdd.reply.send.failed` | `reply_send_failed` | reply.send.failed, message.completed final_status=reply_send_failed, transfer_human.triggered | Yes | Yes | Yes attempted | P0 | Handler returns True but delivery failed. |
| T081-P0-046 | SendMessage 异常 | 普通咨询 | Valid text | SendMessage raises exception | `reply` | `True` | `pdd.reply.send.failed` | `reply_send_failed` | reply.send.failed, message.completed final_status=reply_send_failed | Yes | Yes | Yes attempted | P0 | Must not crash consumer. |
| T081-P0-047 | SendMessage 异常 | 普通咨询 | Valid text | Send call succeeds but no explicit ok | `reply` | `True` | `pdd.reply.send.call_succeeded status=unknown_delivery` | `reply_delivery_unknown` | reply.send.call_succeeded, message.completed final_status=reply_delivery_unknown | Yes | Yes | Yes attempted | P0 | Must not be counted as delivered. |
| T081-P0-048 | human state | 买家再次追问 | Existing `pending_human` conversation | First fallback already sent; second not due | `skip` | `True` | not_called | none | human_lock.skipped, message.skipped | No additional transfer | No | No | P0 | AI should stay silent while waiting for human. |
| T081-P0-049 | human state | 买家再次追问 | Existing `pending_human` conversation | Second reminder window reached | `reply` | `True` | `pdd.reply.send.succeeded` if ok | `reply_sent` | pipeline.completed pending_human_second_fallback, reply.send.succeeded | Yes state remains human | No | Yes | P1 | Confirms second reminder only. |
| T081-P0-050 | human state | 买家多次催促 | Existing `pending_human` conversation | First and second fallback already sent | `skip` | `True` | not_called | none | human_lock.skipped, message.skipped | No additional transfer | No | No | P0 | Fallback throttling must prevent spam. |
| T081-P0-051 | human state | 买家发新问题 | Existing `human_handling` conversation | Human-handling status active | `skip` | `True` | not_called | none | human_lock.skipped, message.skipped | No | No | No | P0 | AI must not抢话. |
| T081-P0-052 | keyword action | 命中自动回复关键词 | Text context | Keyword action=`auto_reply`, reply_text configured | `reply` | `True` | `pdd.reply.send.succeeded` if ok | `reply_sent` | static_rule.matched or pipeline.completed keyword_reply, reply.send.succeeded | No | No | Yes | P0 | Deterministic reply should bypass FastGPT. |
| T081-P0-053 | keyword action | 命中转人工关键词 | Text context | Keyword action=`transfer_human` | `transfer_human` | `True` | transfer reply if sent | `reply_sent` if send ok | transfer_human.triggered, pipeline.completed | Yes | No | Yes | P0 | Must set `pending_human`. |
| T081-P0-054 | keyword action | 命中屏蔽关键词 | Text context | Keyword action=`block` | `block` | `True` | not_called | none | message.skipped action=keyword_block | No | No | No | P0 | T082-A: deterministic silent skip. |

## 6. P0 Must-Test Summary

P0 required cases: 39.

P0 categories:

- Sensitive product suitability and safety.
- Logistics promises.
- Promotions and discounts.
- Refund, exchange, damage, missing item, wrong item.
- Complaint, legal/platform threat, fake product, compensation, media exposure.
- Explicit human-transfer requests.
- Image intercept.
- Missing dataset.
- FastGPT timeout/non-200/empty/unsafe reply.
- PDD send ok/non-ok/exception/unknown delivery.
- Pending human / human handling / fallback throttling.
- Keyword `auto_reply`, `transfer_human`, and `block`.

## 7. Product Decision Items

1. `block` semantics:
   - Recommended: skip silently, no FastGPT, no PDD reply, no transfer.
   - T082-A implemented this default. Any alert/fixed-reply behavior must be a future product policy change.
2. Video, emotion, empty, and unsupported messages:
   - T082-B implemented video fixed reply + human transfer.
   - T082-B implemented emotion lightweight default reply without FastGPT or transfer.
   - T082-B implemented empty and unsupported message skip semantics.
3. Promotions:
   - Define exact approved wording when no coupon/gift/discount exists.
4. Logistics:
   - Define approved wording for “when ship”, “which express”, “why not arrived”, and “urge shipment”.
5. Medical/sensitive product suitability:
   - Define mandatory transfer rules for pregnancy, baby/child use, allergy, adverse reaction, and medical claims.
6. Manual transfer in headless deployment:
   - Decide whether log-only `DummyNotificationService` is sufficient or PushPlus/external alert is mandatory.
7. FastGPT app_id:
   - `FASTGPT_APP_ID` is reserved only and is not used by the current auto-reply runtime.
   - Current FastGPT acceptance depends on `FASTGPT_API_KEY` / DB `fastgpt:api_key` plus each shop's `fastgpt_dataset_id`.
   - Shops without `fastgpt_dataset_id` should transfer to human.

## 8. Next Task Recommendation

T082 workflow 节点补强:

- Clarify ownership of static rules vs DB keywords vs FastGPT workflow.
- Decide handling for video/emotion/empty messages.
- Keep `FASTGPT_APP_ID` out of acceptance scope until the runtime explicitly uses it.
