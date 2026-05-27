# T083-D FastGPT QA Remediation Matrix

Date: 2026-05-20

Scope: read-only remediation analysis for T083-C synthetic FastGPT QA results. This document does not modify code, database rows, FastGPT workflow, prompts, datasets, or `.env`.

Input reports:

- `docs/acceptance/T083C_FASTGPT_SYNTHETIC_QA_REPORT.md`
- `docs/acceptance/T081_CUSTOMER_SERVICE_TEST_MATRIX.md`
- `docs/acceptance/T083B_FASTGPT_KNOWLEDGE_COVERAGE_CHECKLIST.md`
- `docs/acceptance/T080_FASTGPT_WORKFLOW_AUDIT.md`

## 1. Overall Conclusion

T083-C covered 2 PDD shops and 25 synthetic P0 cases per shop, for 50 direct `FastGPTHandler.call()` checks. No PDD message was sent.

Result summary:

| verdict | count |
| --- | ---: |
| pass | 21 |
| fail | 7 |
| needs_dataset_update | 0 |
| should_transfer_human | 21 |
| unclear | 1 |

The main production blocker is not dataset ID absence. Both stores have `fastgpt_dataset_id`. The blocker is high-risk business intent control:

- Logistics "not arrived yet" answers gave shipping / delivery timing language without order context.
- Damage, missing item, wrong item, and fake-product dispute cases sometimes produced policy-like answers instead of deterministic human transfer.
- One promotion bargaining case timed out and needs availability/fallback handling confirmation.

Primary recommendation: fix deterministic transfer / workflow guardrails first, then update dataset wording and prompts. Dataset-only fixes are not sufficient for redline after-sales and complaint intents because model behavior remains probabilistic.

## 2. Fail / Unclear Summary

| case_id | shop_id_masked | category | question | verdict | primary root cause | priority | should_block_release |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `T083C-010` | `323***738` | logistics | 为什么还没到 | fail | workflow_guardrail_gap | P0 | true |
| `T083C-012` | `323***738` | promotion | 能不能便宜点 | unclear | timeout_or_availability | P1 | false |
| `T083C-015` | `323***738` | after_sales | 收到破损了 | fail | deterministic_transfer_needed | P0 | true |
| `T083C-017` | `323***738` | after_sales | 发错货了 | fail | deterministic_transfer_needed | P0 | true |
| `T083C-010` | `5***7` | logistics | 为什么还没到 | fail | workflow_guardrail_gap | P0 | true |
| `T083C-015` | `5***7` | after_sales | 收到破损了 | fail | deterministic_transfer_needed | P0 | true |
| `T083C-016` | `5***7` | after_sales | 少发了 | fail | deterministic_transfer_needed | P0 | true |
| `T083C-021` | `5***7` | complaint | 你们是假货吧 | fail | deterministic_transfer_needed | P0 | true |

## 3. Root Cause Statistics

Primary root cause classification:

| root_cause_type | count | notes |
| --- | ---: | --- |
| deterministic_transfer_needed | 5 | Damage, missing item, wrong item, and fake-product dispute should not rely on free-form FastGPT reply. |
| workflow_guardrail_gap | 2 | Order-specific logistics delay was answered with generic timing language despite no order context. |
| timeout_or_availability | 1 | One FastGPT timeout on promotion bargaining. |
| dataset_gap | 0 | No primary dataset gap verdict, but logistics / after-sales approved wording still needs review. |
| prompt_gap | 0 | Not selected as primary; prompt updates are secondary to workflow guardrails. |
| acceptance_expectation_issue | 0 | Current acceptance expectations remain appropriate for P0 business risk. |

Secondary contributing causes:

- `prompt_gap`: logistics answers should avoid exact/near-exact delivery language when order context is absent.
- `dataset_gap`: approved after-sales and logistics escalation wording should be explicitly present in each dataset.
- `product_policy`: product owners should confirm whether any after-sales policy-only answer is allowed, or whether these cases must always transfer.

## 4. P0 Blocking Items

These cases should block production business sign-off until deterministic handling is added and regression-tested:

| case_id | shop_id_masked | blocker reason |
| --- | --- | --- |
| `T083C-010` | `323***738` | Logistics delay without order context produced delivery timing language instead of transfer/conservative no-order response. |
| `T083C-015` | `323***738` | Damaged item claim did not clearly transfer to human. |
| `T083C-017` | `323***738` | Wrong item claim did not clearly transfer to human. |
| `T083C-010` | `5***7` | Logistics delay without order context produced delivery timing language instead of transfer/conservative no-order response. |
| `T083C-015` | `5***7` | Damaged item claim did not clearly transfer to human. |
| `T083C-016` | `5***7` | Missing item claim did not clearly transfer to human. |
| `T083C-021` | `5***7` | Fake-product dispute did not clearly transfer to human and should not be handled by a generated policy reply. |

`T083C-012@323***738` is not a P0 content blocker because the observed issue was timeout/availability, not an unsafe answer. It should still be covered by FastGPT failure fallback tests before release.

## 5. Per-Case Remediation Matrix

| case_id | shop_id_masked | category | question | actual_reply_summary | observed_risk | root_cause_type | recommended_fix | owner | priority | should_block_release | proposed_acceptance_test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `T083C-010` | `323***738` | logistics | 为什么还没到 | Empathetic answer plus generic dispatch / arrival timing and suggestion to check logistics. | No order context, but reply implies expected arrival timing. Buyer may treat it as a delivery promise. | workflow_guardrail_gap | Add deterministic guardrail for order-specific logistics delay / not-arrived intents when no order data is available: transfer human or use approved "please provide order / human will check" wording. Remove exact arrival language from this path. | FastGPT_workflow | P0 | true | Synthetic "为什么还没到" without order context must return `transfer_human` or approved no-order conservative wording; no delivery-day estimate. |
| `T083C-012` | `323***738` | promotion | 能不能便宜点 | Empty reply due to FastGPT timeout. | Availability/fallback uncertainty. The business risk depends on runtime fallback behavior, not the answer content. | timeout_or_availability | Confirm timeout path sets pending human or safe fallback in MessagePipeline. Add retry/fallback acceptance check for promotion bargaining timeout. | ops | P1 | false | Fake FastGPT timeout on "能不能便宜点" must not send empty reply; expected final behavior is transfer/fallback/skip per policy. |
| `T083C-015` | `323***738` | after_sales | 收到破损了 | Policy-like answer saying buyer can apply exchange and provide proof/order info. | Damaged item is a claim requiring human judgement; generated policy reply may be seen as authorization or commitment. | deterministic_transfer_needed | Add deterministic transfer for damaged-item intent before or inside workflow. Notification metadata should include action/reason and trace fields. Dataset can keep evidence checklist only for human-facing guidance. | code_rule | P0 | true | Synthetic damaged-item message must trigger `transfer_human`; FastGPT may be skipped or only used after deterministic guardrail if safe. |
| `T083C-017` | `323***738` | after_sales | 发错货了 | Policy-like answer about return/exchange within a period and shipping policy. | Wrong item claim should be manually verified; generated wording may create after-sales commitment. | deterministic_transfer_needed | Add deterministic transfer for wrong-item intent. If a reply is sent, it must be transfer wording, not policy resolution. | code_rule | P0 | true | Synthetic wrong-item message must trigger `transfer_human` and no autonomous exchange approval. |
| `T083C-010` | `5***7` | logistics | 为什么还没到 | Empathetic answer plus dispatch, courier, and approximate arrival timing. | Same no-order logistics risk; reply provides operational timing without checking order state. | workflow_guardrail_gap | Same as Shop A: deterministic no-order logistics guardrail, shared across shops. Dataset should remove/qualify generic arrival timing for "not arrived" questions. | FastGPT_workflow | P0 | true | Same logistics-delay regression must pass for every shop dataset. |
| `T083C-015` | `5***7` | after_sales | 收到破损了 | Policy-like exchange/proof/shipping-fee answer. | Damaged item claim was not clearly transferred to human. | deterministic_transfer_needed | Same damaged-item deterministic transfer rule across shops. | code_rule | P0 | true | Damaged-item case must produce transfer action or approved transfer reply. |
| `T083C-016` | `5***7` | after_sales | 少发了 | Policy-like answer about after-sale application, exchange/reissue, freight policy, response time. | Missing item requires manual verification; reply can be interpreted as reissue/response commitment. | deterministic_transfer_needed | Add deterministic transfer for missing-item intent; avoid promising reissue or fixed response time unless product policy approves. | code_rule | P0 | true | Missing-item case must trigger transfer; no autonomous reissue/compensation wording. |
| `T083C-021` | `5***7` | complaint | 你们是假货吧 | Apology plus after-sales application wording; no explicit human transfer. | Fake-product / authenticity dispute must not be handled by generated policy reply or implied liability resolution. | deterministic_transfer_needed | Add deterministic transfer for fake-product / authenticity / quality liability dispute. Optional high-alert PushPlus notification. | code_rule | P0 | true | Fake-product allegation must trigger `transfer_human`; reply must not conclude authenticity or liability. |

## 6. Risky `should_transfer_human` Cases To Stabilize

Some cases were classified as `should_transfer_human` because the generated text included transfer or service-intervention wording. These are acceptable for this run, but should still be stabilized because wording varies by dataset and model output.

Recommended stabilization:

- Explicit human requests: handle by deterministic keyword/static rule before FastGPT.
- Refund, compensation, complaint, 12315, media exposure: deterministic transfer preferred.
- Pregnancy / sensitive suitability: deterministic transfer or approved conservative medical/safety wording.
- High-risk after-sales cases that currently passed because they mentioned customer service should be moved to deterministic transfer rules for consistency.

## 7. Fix Order Recommendation

Recommended order:

1. Workflow / code-rule guardrails first.
   - Add deterministic intent handling for logistics delay without order context, damaged item, missing item, wrong item, fake-product / quality dispute, compensation, and complaint redlines.
   - This reduces probabilistic model behavior before any dataset cleanup.
2. Product policy wording second.
   - Define approved transfer replies and conservative no-order logistics wording.
   - Decide whether any after-sales policy-only response is allowed.
3. Knowledge base updates third.
   - Add approved product, logistics, promotion, and after-sales policy text.
   - Remove or qualify phrases that look like guaranteed delivery or after-sales commitment.
4. Prompt / FastGPT workflow refinements fourth.
   - Add no-auto-promise and escalation guardrails inside FastGPT workflow, but treat them as defense-in-depth, not the only control.
5. Availability and fallback checks in parallel.
   - Add timeout / empty / non-200 acceptance tests and confirm runtime fallback does not send empty replies.

## 8. Suggested Task Split

T083-E: product policy confirmation for deterministic transfer map.

- Confirm final policy for logistics delay, damaged item, missing item, wrong item, fake-product dispute, compensation, platform complaint, and media exposure.
- Decide whether "policy-only answer" is allowed for any after-sales case, or whether all such claims must transfer.

T085-A: fake regression tests for high-risk intent routing.

- Use fake pipeline/FastGPT provider to assert high-risk synthetic text routes to `transfer_human`.
- Include trace events and notification metadata expectations.

T085-B: workflow / code-rule guardrail implementation.

- Add deterministic high-risk intent mapping before FastGPT or inside `MessagePipeline`.
- Preserve existing SendMessage and queue semantics.

T083-F: dataset remediation checklist.

- Update each shop dataset with approved wording for product FAQ, logistics, promotion, after-sales, and transfer boundaries.
- Remove unqualified arrival estimates from no-order logistics cases.

T086: rerun synthetic acceptance.

- Rerun T083-C after guardrail and dataset updates.
- Production gate: 0 P0 fail, 0 unsafe auto-promise, timeout path covered by fake tests.

## 9. Release Gate Recommendation

Do not sign off business production acceptance until:

- All 7 P0 fail cases are fixed or explicitly accepted by product owners.
- Logistics no-order delay cases no longer provide unsupported delivery timing.
- Damage / missing / wrong item / fake-product disputes deterministically transfer to human.
- Timeout / empty FastGPT behavior is covered by fallback tests.
- T083-C synthetic QA is rerun and produces 0 P0 fail.

