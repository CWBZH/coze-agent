from pathlib import Path

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.

from Message.workflow.sop_loader import load_sop_markdown, parse_sop_markdown


NORMAL_MARKDOWN = """---
shop_id: synthetic-shop-1
version: sop-test-v1
---

## Logistics ETA
kb_item_id: sop-logistics-001
domain: logistics_policy
title: Logistics ETA boundary
intent_examples:
- Where is my package?
- Can you promise delivery tomorrow?
approved_answer: |
  Please check the order logistics page for the latest carrier status.
  I can transfer you to support if the tracking page is unclear.
forbidden_phrases:
- guaranteed delivery tomorrow
- already delivered
should_transfer_human: false
risk_level: low

## After-sales evidence
kb_item_id: sop-after-sales-001
domain: after_sales_evidence
title: Evidence request
intent_examples:
- The item is damaged.
approved_answer: |
  Please provide clear photos of the product, package, and shipping label.
forbidden_phrases:
- refund approved
should_transfer_human: true
risk_level: medium

## Promotion policy
kb_item_id: sop-promotion-001
domain: promotion_policy
title: Promotion and coupon boundary
intent_examples:
- Can you give me a discount?
approved_answer: |
  Please guide the buyer to check the product page and checkout page for current promotions.
forbidden_phrases:
- private discount
should_transfer_human: false
risk_level: medium

## Redline escalation
kb_item_id: sop-redline-001
domain: redline_escalation
title: Complaint and platform dispute escalation
intent_examples:
- I will report your shop.
approved_answer: |
  Keep the reply neutral and transfer to human support for complaint handling.
forbidden_phrases:
- compensation guaranteed
should_transfer_human: true
risk_level: high

## Sensitive user safety
kb_item_id: sop-sensitive-001
domain: sensitive_user_safety
title: Sensitive user safety boundary
intent_examples:
- Can a pregnant customer use this?
approved_answer: |
  Do not provide medical or safety guarantees.
forbidden_phrases:
- guaranteed safe
should_transfer_human: true
risk_level: high
"""

SOP_DOMAINS = {
    "logistics_policy",
    "after_sales_evidence",
    "promotion_policy",
    "redline_escalation",
    "sensitive_user_safety",
}


def test_loads_normal_markdown_with_metadata(tmp_path: Path):
    path = tmp_path / "sop.md"
    path.write_text(NORMAL_MARKDOWN, encoding="utf-8")

    result = load_sop_markdown(path)

    assert result.errors == []
    assert result.metadata == {"shop_id": "synthetic-shop-1", "version": "sop-test-v1"}
    assert len(result.records) == 5
    first = result.records[0]
    assert first.kb_item_id == "sop-logistics-001"
    assert first.domain == "logistics_policy"
    assert first.shop_id == "synthetic-shop-1"
    assert first.version == "sop-test-v1"
    assert first.intent_examples == ["Where is my package?", "Can you promise delivery tomorrow?"]
    assert "latest carrier status" in first.approved_answer
    assert first.should_transfer_human is False
    assert len(first.content_hash) == 64
    assert {record.version for record in result.records} == {"sop-test-v1"}


def test_supports_multiple_domains():
    result = parse_sop_markdown(NORMAL_MARKDOWN)

    domains = {record.domain for record in result.records}

    assert domains == SOP_DOMAINS


def test_missing_required_field_reports_error_without_crashing():
    markdown = """## Bad SOP
kb_item_id: sop-bad-001
domain: promotion_policy
title: Missing answer
intent_examples:
- Any coupon?
forbidden_phrases:
- private discount
should_transfer_human: false
risk_level: high
version: v1
"""

    result = parse_sop_markdown(markdown)

    assert result.records == []
    assert any(error.field == "approved_answer" and "missing" in error.message for error in result.errors)


def test_content_hash_is_stable_for_same_content():
    first = parse_sop_markdown(NORMAL_MARKDOWN)
    second = parse_sop_markdown(NORMAL_MARKDOWN)

    assert first.records[0].content_hash == second.records[0].content_hash
    assert first.records[1].content_hash == second.records[1].content_hash


def test_domain_filter_returns_only_matching_records():
    result = parse_sop_markdown(NORMAL_MARKDOWN, domains=["after_sales_evidence"])

    assert result.errors == []
    assert [record.domain for record in result.records] == ["after_sales_evidence"]


def test_loader_does_not_log_full_sop_content(caplog):
    secret_text = "SECRET_FULL_SOP_CONTENT_DO_NOT_LOG"
    markdown = f"""## Sensitive user safety
kb_item_id: sop-sensitive-001
domain: sensitive_user_safety
title: Sensitive user boundary
intent_examples:
- Can a pregnant customer use this?
approved_answer: |
  {secret_text}
forbidden_phrases:
- guaranteed safe
should_transfer_human: true
risk_level: high
version: v1
"""

    result = parse_sop_markdown(markdown)

    assert result.errors == []
    assert secret_text in result.records[0].approved_answer
    assert secret_text not in caplog.text
