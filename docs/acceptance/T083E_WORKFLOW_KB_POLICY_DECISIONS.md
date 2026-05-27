# T083-E FastGPT Workflow And Knowledge Base Policy Decisions

Date: 2026-05-20

Scope: phase-one business policy decision document for FastGPT workflow and knowledge base remediation. This document does not modify code, database rows, FastGPT workflow, prompts, datasets, or `.env`.

Related documents:

- `docs/acceptance/T080_FASTGPT_WORKFLOW_AUDIT.md`
- `docs/acceptance/T081_CUSTOMER_SERVICE_TEST_MATRIX.md`
- `docs/acceptance/T083B_FASTGPT_KNOWLEDGE_COVERAGE_CHECKLIST.md`
- `docs/acceptance/T083C_FASTGPT_SYNTHETIC_QA_REPORT.md`
- `docs/acceptance/T083D_FASTGPT_QA_REMEDIATION_MATRIX.md`

## 1. Phase-One Review Conclusion

After product review, the phase-one acceptance direction is:

- Code should not replace the FastGPT workflow as the primary business decision layer.
- FastGPT workflow should own intent routing, knowledge retrieval, and standard customer-service wording.
- Code should remain a safety fallback and observability layer: missing dataset, FastGPT failure, unsafe reply, delivery failure, media intercepts, trace logs, and notification isolation.
- After-sales cases such as damaged item, missing item, and wrong item may be handled by FastGPT workflow first, using the after-sales knowledge base to request photos, order information, and evidence.
- After the buyer sends images or evidence, human review is required.
- Logistics questions may answer store-level dispatch policy and approximate general shipping time, but must not claim the specific order's live logistics state without order context.
- Fake-product disputes, complaints, 12315, compensation, and media exposure must route to human service or high-priority human escalation.

This document supersedes the strict T083-D recommendation that all damaged / missing / wrong item cases must be deterministic code-level transfer. For phase one, those cases should be routed by workflow to the after-sales knowledge branch and request evidence, with code retaining fallback and safety controls.

## 2. T083-C Fail / Unclear Re-Attribution

| case_id | shop_id_masked | category | previous T083-D cause | phase-one decision cause | decision |
| --- | --- | --- | --- | --- | --- |
| `T083C-010` | `323***738` | logistics | workflow_guardrail_gap | workflow wording / policy boundary gap | Logistics workflow may answer general dispatch and approximate timing, but must clearly say specific order status follows the order logistics page or human check. |
| `T083C-012` | `323***738` | promotion | timeout_or_availability | timeout_or_availability | Keep as availability/fallback issue. It does not prove a knowledge defect. |
| `T083C-015` | `323***738` | after_sales | deterministic_transfer_needed | workflow_after_sales_branch_gap + dataset_gap | Damaged item may be handled by after-sales workflow first, but reply should request damage photos and order/evidence; image evidence then routes to human review. |
| `T083C-017` | `323***738` | after_sales | deterministic_transfer_needed | workflow_after_sales_branch_gap + dataset_gap | Wrong item may be handled by after-sales workflow first, but reply should request real item photo, order info, and wrong-item description; human reviews evidence. |
| `T083C-010` | `5***7` | logistics | workflow_guardrail_gap | workflow wording / policy boundary gap | Same logistics boundary: general policy is allowed; specific order state is not. |
| `T083C-015` | `5***7` | after_sales | deterministic_transfer_needed | workflow_after_sales_branch_gap + dataset_gap | Damaged item workflow should request clear damage photo and package/order proof. |
| `T083C-016` | `5***7` | after_sales | deterministic_transfer_needed | workflow_after_sales_branch_gap + dataset_gap | Missing item workflow should request package photo, received items photo, missing item description, and order info. |
| `T083C-021` | `5***7` | complaint | deterministic_transfer_needed | deterministic_human_escalation_needed | Fake-product dispute must not be answered by generic after-sales wording; route to human service / high-priority alert. |

Revised root-cause summary:

| root_cause_type | count | meaning |
| --- | ---: | --- |
| workflow_after_sales_branch_gap + dataset_gap | 4 | After-sales branch should request evidence before human review. |
| workflow wording / policy boundary gap | 2 | Logistics wording must separate general policy from specific order status. |
| deterministic_human_escalation_needed | 1 | Fake-product dispute remains redline human escalation. |
| timeout_or_availability | 1 | FastGPT timeout/fallback behavior should be verified separately. |

## 3. FastGPT Workflow Branch Design Recommendation

The phase-one workflow should route buyer intents into explicit branches before drafting replies.

| branch | representative intents | allowed behavior | required guardrails |
| --- | --- | --- | --- |
| `product_basic` | price, specs, usage, ingredients, shelf life | Answer from product knowledge. Ask clarification if product is unclear. | Do not invent price, specs, gifts, or safety claims. |
| `logistics_policy` | when ship, which courier, general delivery time | Answer store-level dispatch policy and approximate general timing if approved in knowledge base. | Must say actual logistics/order page prevails. No specific order state without order data. |
| `logistics_order_status` | why not arrived, delay, no tracking update | Provide general policy and ask buyer to check order logistics or wait for human check. | Do not say the specific package has arrived, is delayed for a known reason, or will arrive on a specific date. |
| `promotion_policy` | coupon, discount, gift, bargaining | Use page activity / store policy. | No private discount, no invented coupon, no invented gift. |
| `after_sales_evidence_collection` | damaged item, missing item, wrong item | Request required evidence and explain human review after evidence is received. | Do not approve refund/exchange/reissue automatically. Do not promise compensation. |
| `human_escalation_redline` | fake product, complaint, 12315, compensation, media exposure, legal threat | Transfer to human service / high-priority alert. | No authenticity conclusion, liability conclusion, legal outcome, or compensation amount. |
| `explicit_human_request` | transfer human, find customer service | Transfer human. | Avoid continuing AI answer after transfer state is set. |
| `fallback` | unknown, unsupported, low-confidence | Ask clarification or transfer depending on risk. | No unsupported factual commitment. |

## 4. Knowledge Base Supplement Checklist

The knowledge base should add or verify these entries per shop.

### Product And Policy Basics

- Product names, aliases, and applicable product categories.
- Price policy: page price and active platform activity prevail.
- Spec list and variant explanation.
- Usage method and safe-use notes.
- Ingredients / components, with no unsupported medical or safety claims.
- Shelf life and storage conditions.
- Sensitive-user policy: pregnancy, children, allergy, adverse reaction.

### Logistics

- Dispatch policy, for example approved wording for "ships within N hours" if true.
- Shipping origin.
- Default courier policy.
- Remote-area and holiday exceptions.
- Approximate general shipping time if approved.
- Required boundary sentence: actual order logistics and platform tracking prevail.
- No-order-context wording for "why has it not arrived".

### Promotion

- Coupon / discount policy.
- Gift policy.
- Free shipping policy.
- Bargaining / private discount policy.
- Required boundary sentence: page activity and platform checkout price prevail.

### After-Sales Evidence Collection

- Damaged item: request damage photos, outer package photo if needed, order number/order screenshot if allowed by platform, and issue description.
- Missing item: request received item photo, package photo, missing item description, and order information.
- Wrong item: request received product photo, product label/spec photo, order information, and expected item description.
- Explain that human customer service will review evidence.
- Do not promise refund, exchange, reissue, freight compensation, or approval result.

### Redline Human Escalation

- Fake-product / authenticity dispute.
- Platform complaint / 12315 / legal threat.
- Compensation demand.
- Media exposure.
- Severe quality or safety dispute.
- Required wording: acknowledge concern, transfer human, avoid conclusion.

## 5. Intent Reply Strategy

| intent | phase-one strategy | FastGPT call allowed | human transfer |
| --- | --- | --- | --- |
| `damaged_item` | After-sales evidence-collection branch asks for damage photo and proof. | yes | after evidence or if buyer escalates |
| `missing_item` | Ask for package/item photo and missing-item description. | yes | after evidence or if buyer escalates |
| `wrong_item` | Ask for real item photo and order info. | yes | after evidence or if buyer escalates |
| `logistics_policy` | Answer store-level dispatch/courier/general timing. | yes | no by default |
| `logistics_order_status` / `no_arrival` | Give general policy and say actual order logistics prevails; transfer or ask human to check if buyer needs specific order status. | yes | maybe |
| `fake_product` | Human escalation; no authenticity conclusion. | no or guarded workflow transfer only | yes |
| `complaint` / `12315` | Human escalation; no legal/platform outcome promise. | no or guarded workflow transfer only | yes |
| `compensation` | Human escalation; no amount or approval promise. | no or guarded workflow transfer only | yes |
| `media_exposure` | Human escalation; no argument. | no or guarded workflow transfer only | yes |
| `promotion_bargaining` | Use page activity / platform price; no private discount. | yes | maybe if buyer insists |

## 6. When To Request Evidence

Request evidence when the buyer describes an after-sales factual claim that cannot be verified from the message alone:

- damaged item,
- missing item,
- wrong item,
- leakage / broken package,
- unclear product quality defect,
- suspected wrong spec or wrong quantity.

Allowed evidence request fields:

- photo of damaged or received item,
- photo of package / outer box when relevant,
- short issue description,
- order information when platform-safe and necessary.

Do not ask for credentials, passwords, payment secrets, or private information unrelated to after-sales handling.

After evidence is provided:

- Image messages are already handled by code-level image intercept with fixed reply and transfer.
- Human review should decide refund, replacement, reissue, freight, or liability.

## 7. When To Transfer Human

Must transfer human:

- fake-product or authenticity dispute,
- explicit platform complaint,
- 12315 / legal threat,
- compensation demand,
- media exposure threat,
- buyer explicitly asks for human service,
- FastGPT missing dataset, timeout/non-200/empty after fallback policy,
- unsafe generated reply,
- SendMessage failed or delivery unknown when intervention is required,
- after-sales evidence has been provided and requires review.

May transfer human:

- logistics order-specific status check without order context,
- promotion bargaining after buyer insists,
- medical/sensitive suitability questions,
- ambiguous high-risk product quality complaint.

## 8. No-Auto-Promise Boundary

The AI workflow must not automatically promise:

- refund approval,
- exchange approval,
- reissue approval,
- freight compensation,
- compensation amount,
- private discount,
- coupon / gift / free shipping not explicitly in the page or dataset,
- guaranteed dispatch beyond approved store policy,
- guaranteed arrival date,
- specific order logistics state without order context,
- authenticity conclusion,
- quality liability conclusion,
- platform/legal/12315 outcome,
- medical or safety guarantee.

## 9. Code Boundary Decision

Code remains responsible for safety fallback and deterministic non-business infrastructure behavior:

- missing `fastgpt_dataset_id` should not call FastGPT,
- FastGPT timeout/non-200/empty should not send unsafe empty content,
- unsafe reply should be replaced or escalated,
- media intercepts remain deterministic,
- SendMessage final status remains observable,
- PushPlus/headless notification remains isolated from main processing,
- trace/log privacy rules remain enforced.

Code should not hardcode every business policy if FastGPT workflow can route and answer safely. Business wording and first-level after-sales evidence collection belong in FastGPT workflow and knowledge base.

## 10. Next Tasks

T083-F: knowledge base supplement.

- Add the phase-one logistics, promotion, after-sales evidence, and redline escalation wording to each shop dataset.
- Use the no-auto-promise boundary as required dataset policy.

T083-G: FastGPT workflow adjustment.

- Add explicit branch routing for `logistics_policy`, `logistics_order_status`, `promotion_policy`, `after_sales_evidence_collection`, and `human_escalation_redline`.
- Ensure redline escalation does not produce generic after-sales answers.

T083-H: second synthetic QA acceptance.

- Rerun T083-C after dataset/workflow updates.
- Acceptance target: no redline auto-answer, no unsupported logistics order status, no private discount/gift invention, after-sales evidence collection wording present.

T085: runtime regression tests.

- Keep fake tests for code fallback paths: missing dataset, FastGPT failure/empty, unsafe reply, SendMessage failed/unknown delivery, image/video/emotion/empty, keyword block.

