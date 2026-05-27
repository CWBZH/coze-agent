# T083-B FastGPT Knowledge Coverage Checklist

Date: 2026-05-20

Scope: business acceptance checklist for FastGPT dataset knowledge coverage. This document does not modify code, database rows, FastGPT configuration, prompts, or `.env`.

Status vocabulary:

- `required`: must exist in the dataset or policy source before production acceptance.
- `present`: confirmed present by audit or test.
- `missing`: confirmed absent.
- `unclear`: not yet verified by dataset inspection or synthetic question.
- `must_transfer_human`: AI must not answer automatically; route to human service.
- `not_applicable`: not relevant for the shop or scenario.

Sensitive data policy:

- Shop id, user id, and dataset id are shown only in redacted form.
- No token, cookie, access token, password, API key, or full dataset id is included.
- All future test questions should be synthetic and must not use real buyer private data.

## 1. Overall Conclusion

T083-A confirmed that the local database contains two pinduoduo shops and both have non-empty `shops.fastgpt_dataset_id` values. That means both shops are eligible for the FastGPT route from a configuration-readiness perspective.

Dataset quality remains unverified. The following business knowledge areas must be validated per shop before production business sign-off:

- product basics,
- product context behavior,
- logistics wording,
- promotions and no-invention rules,
- after-sales and refund policy,
- complaint / high-risk handling,
- transfer-to-human boundaries,
- no-auto-promise policy.

## 2. Dataset Coverage Table By Shop

### Shop A

| Field | Value |
| --- | --- |
| shop_id | `323***738` |
| user_id | `163***769` |
| dataset_id | `6a0854...6dcd` |
| account candidate enabled | yes, local `accounts.status == 1` |
| FastGPT route readiness | `present` for dataset id; knowledge content `unclear` |

| Dimension | Required status | Current status | Acceptance requirement |
| --- | --- | --- | --- |
| Product names | required | unclear | Dataset must include production product names and aliases. |
| Specs | required | unclear | Answer only available specs; ask clarification if product context is missing. |
| Price wording | required | unclear | Must not invent prices; refer to page/order activity when exact price is dynamic. |
| Usage method | required | unclear | Must be safe, concise, and product-specific. |
| Ingredients | required | unclear | Must avoid medical or unsupported safety claims. |
| Shelf life | required | unclear | Must answer only if policy/data is present. |
| Suitable users | required | unclear | Sensitive suitability should be conservative or transfer. |
| Contraindications / notes | required | unclear | Pregnancy, child use, allergy, adverse reaction, and medical claims should transfer unless explicitly approved. |
| goods_id context | required | unclear | Product card / goods id should guide the answer when available. |
| No goods context | required | unclear | Ask which product instead of guessing. |
| Multi-turn follow-up | required | unclear | Use recent session context without hallucinating unavailable product facts. |
| Shipping time | required | unclear | Must not guarantee unsupported dispatch time. |
| Courier | required | unclear | Use policy wording or state that actual logistics prevail. |
| Urge shipment | required | unclear | Avoid promising immediate dispatch unless explicitly supported. |
| Delayed / not arrived | required | unclear | Transfer or use conservative policy wording when order details are unavailable. |
| Coupons | required | unclear | Do not invent coupons. |
| Gifts | required | unclear | Do not invent gifts. |
| Free shipping | required | unclear | Do not invent shipping benefits. |
| Bargaining | required | unclear | Do not offer private discounts unless policy allows it. |
| Refund flow | required | unclear | High-risk refund approval must transfer human. |
| Exchange flow | required | unclear | Use approved policy wording or transfer. |
| Damaged item | must_transfer_human | must_transfer_human | Human handling expected. |
| Missing / wrong item | must_transfer_human | must_transfer_human | Human handling expected. |
| Bad review / platform complaint / 12315 | must_transfer_human | must_transfer_human | No argumentative or legal commitment response. |
| Fake-product / quality dispute | must_transfer_human | must_transfer_human | Do not make authenticity or liability conclusions automatically. |
| Compensation / media exposure | must_transfer_human | must_transfer_human | Do not promise compensation or legal outcomes. |
| Image message | not_applicable | present | Code-level intercept handles image with fixed reply + transfer; not a dataset dependency. |
| Video message | not_applicable | present | Code-level intercept handles video with fixed reply + transfer; not a dataset dependency. |
| Emotion message | not_applicable | present | Code-level default reply; not a dataset dependency. |
| Empty / unsupported message | not_applicable | present | Code-level skip; not a dataset dependency. |

### Shop B

| Field | Value |
| --- | --- |
| shop_id | `565***617` |
| user_id | `713***439` |
| dataset_id | `6a0855...77b4` |
| account candidate enabled | yes, local `accounts.status == 1` |
| FastGPT route readiness | `present` for dataset id; knowledge content `unclear` |

| Dimension | Required status | Current status | Acceptance requirement |
| --- | --- | --- | --- |
| Product names | required | unclear | Dataset must include production product names and aliases. |
| Specs | required | unclear | Answer only available specs; ask clarification if product context is missing. |
| Price wording | required | unclear | Must not invent prices; refer to page/order activity when exact price is dynamic. |
| Usage method | required | unclear | Must be safe, concise, and product-specific. |
| Ingredients | required | unclear | Must avoid medical or unsupported safety claims. |
| Shelf life | required | unclear | Must answer only if policy/data is present. |
| Suitable users | required | unclear | Sensitive suitability should be conservative or transfer. |
| Contraindications / notes | required | unclear | Pregnancy, child use, allergy, adverse reaction, and medical claims should transfer unless explicitly approved. |
| goods_id context | required | unclear | Product card / goods id should guide the answer when available. |
| No goods context | required | unclear | Ask which product instead of guessing. |
| Multi-turn follow-up | required | unclear | Use recent session context without hallucinating unavailable product facts. |
| Shipping time | required | unclear | Must not guarantee unsupported dispatch time. |
| Courier | required | unclear | Use policy wording or state that actual logistics prevail. |
| Urge shipment | required | unclear | Avoid promising immediate dispatch unless explicitly supported. |
| Delayed / not arrived | required | unclear | Transfer or use conservative policy wording when order details are unavailable. |
| Coupons | required | unclear | Do not invent coupons. |
| Gifts | required | unclear | Do not invent gifts. |
| Free shipping | required | unclear | Do not invent shipping benefits. |
| Bargaining | required | unclear | Do not offer private discounts unless policy allows it. |
| Refund flow | required | unclear | High-risk refund approval must transfer human. |
| Exchange flow | required | unclear | Use approved policy wording or transfer. |
| Damaged item | must_transfer_human | must_transfer_human | Human handling expected. |
| Missing / wrong item | must_transfer_human | must_transfer_human | Human handling expected. |
| Bad review / platform complaint / 12315 | must_transfer_human | must_transfer_human | No argumentative or legal commitment response. |
| Fake-product / quality dispute | must_transfer_human | must_transfer_human | Do not make authenticity or liability conclusions automatically. |
| Compensation / media exposure | must_transfer_human | must_transfer_human | Do not promise compensation or legal outcomes. |
| Image message | not_applicable | present | Code-level intercept handles image with fixed reply + transfer; not a dataset dependency. |
| Video message | not_applicable | present | Code-level intercept handles video with fixed reply + transfer; not a dataset dependency. |
| Emotion message | not_applicable | present | Code-level default reply; not a dataset dependency. |
| Empty / unsupported message | not_applicable | present | Code-level skip; not a dataset dependency. |

## 3. Knowledge Items That Must Be Filled Or Verified

The following items are required for each production shop dataset unless the shop explicitly does not sell products that need that category.

| Area | Required knowledge | Current audit status |
| --- | --- | --- |
| Product basics | Product names, aliases, specs, prices or price policy, usage, ingredients, shelf life, suitable users | unclear |
| Safety / suitability | Contraindications, allergy notes, pregnancy / child / sensitive user policy, adverse reaction response | unclear |
| Product context | goods_id mapping, product card handling, no-product clarification wording, multi-turn follow-up behavior | unclear |
| Logistics | Dispatch time, courier policy, delayed shipment wording, no guaranteed arrival unless supported | unclear |
| Promotions | Coupon policy, gifts, shipping fee policy, bargaining policy, no private discount promise | unclear |
| After-sales | Refund process, exchange process, damage / missing / wrong item handling, evidence requirements | unclear |
| Complaint redlines | Bad review, 12315, platform complaint, fake-product claim, compensation, media exposure | must_transfer_human |
| Transfer wording | Approved transfer-to-human reply text for high-risk and uncertain cases | unclear |

## 4. Mandatory Transfer-To-Human Scenarios

The following scenarios must route to human unless a later product decision explicitly approves a deterministic safe reply:

- explicit request for human service,
- missing `fastgpt_dataset_id`,
- FastGPT timeout / non-200 / empty answer after fallback policy,
- AI uncertainty on high-risk questions,
- refund approval or compensation request,
- damaged item, missing item, wrong item,
- platform complaint, 12315, legal threat,
- fake-product or quality liability dispute,
- media exposure threat,
- unsafe generated reply,
- SendMessage failed or delivery unknown when intervention is required.

## 5. No-Auto-Promise List

The AI must not automatically promise:

- refund approval,
- compensation amount,
- private discount or off-platform deal,
- coupon / gift / free shipping that is not explicitly in the dataset,
- guaranteed dispatch time,
- guaranteed delivery or arrival time,
- legal / platform complaint result,
- authenticity conclusion for fake-product claims,
- quality liability conclusion,
- medical or adverse-reaction conclusion.

## 6. T083-C Synthetic FastGPT QA Acceptance Recommendation

T083-C should run a synthetic question set against each configured dataset and record:

- shop label,
- redacted dataset id,
- synthetic buyer question,
- required context (`goods_id`, product card, multi-turn, no context),
- expected action (`reply`, `transfer_human`, `message.skipped`),
- expected no-auto-promise checks,
- expected trace events,
- whether FastGPT should be called,
- answer quality result: pass / fail / needs dataset update,
- notes for dataset owners.

Recommended minimum cases per shop:

- 3 basic greetings,
- 8 product basic questions,
- 4 product context questions,
- 4 logistics questions,
- 4 promotion questions,
- 5 after-sales questions,
- 6 complaint / high-risk questions,
- 4 transfer-to-human questions,
- 5 abnormal / fallback cases.

Minimum production gate:

- all P0 high-risk cases transfer or use approved safe wording,
- no invented discounts, logistics promises, refund approvals, or compensation promises,
- product FAQ answers are grounded in the dataset,
- missing knowledge causes clarification or transfer instead of hallucination.
