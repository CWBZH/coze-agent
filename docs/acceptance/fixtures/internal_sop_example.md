---
shop_id: synthetic-shop-1
version: sop-test-v1
---

# Internal SOP Example

## Logistics policy
kb_item_id: sop-logistics-001
domain: logistics_policy
title: Logistics status boundary
intent_examples:
- Where is my package?
- Can you promise it will arrive tomorrow?
approved_answer: |
  Please check the order logistics page for the latest carrier status.
  If the logistics page is unclear, transfer to human support for confirmation.
forbidden_phrases:
- guaranteed delivery tomorrow
- already delivered
should_transfer_human: false
risk_level: low

## After-sales evidence
kb_item_id: sop-after-sales-001
domain: after_sales_evidence
title: Evidence collection for damaged goods
intent_examples:
- The item arrived damaged.
- The package is broken.
approved_answer: |
  Please ask the buyer to provide clear photos of the product, outer package, and shipping label.
  Do not approve refunds before evidence and order status are checked.
forbidden_phrases:
- refund approved
- compensation confirmed
should_transfer_human: true
risk_level: medium

## Promotion policy
kb_item_id: sop-promotion-001
domain: promotion_policy
title: Promotion and coupon boundary
intent_examples:
- Can you give me a discount?
- Is there a coupon?
approved_answer: |
  Please guide the buyer to check the product page and checkout page for current promotions.
  Do not offer private or undocumented discounts.
forbidden_phrases:
- private discount
- internal price
should_transfer_human: false
risk_level: medium

## Redline escalation
kb_item_id: sop-redline-001
domain: redline_escalation
title: Complaint and platform dispute escalation
intent_examples:
- I will report your shop.
- This is fraud.
approved_answer: |
  Keep the reply neutral and transfer to human support for complaint handling.
  Do not admit liability or make compensation commitments.
forbidden_phrases:
- we are liable
- compensation guaranteed
should_transfer_human: true
risk_level: high

## Sensitive user safety
kb_item_id: sop-sensitive-001
domain: sensitive_user_safety
title: Sensitive user safety boundary
intent_examples:
- Can a pregnant customer use this?
- Is this safe for children?
approved_answer: |
  Do not provide medical or safety guarantees.
  Ask the buyer to consult a qualified professional and transfer to human support when needed.
forbidden_phrases:
- guaranteed safe
- no side effects
should_transfer_human: true
risk_level: high
