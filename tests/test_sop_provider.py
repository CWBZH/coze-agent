import logging
from pathlib import Path

import pytest
import Session.session_manager  # Import order avoids existing core/logger circular import in tests.

from Message.workflow.sop_provider import SOPProvider


ACCEPTANCE_SOP_FIXTURE = (
    Path(__file__).resolve().parents[1] / "docs" / "acceptance" / "fixtures" / "internal_sop_example.md"
)

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
approved_answer: |
  Please check the order logistics page for the latest carrier status.
forbidden_phrases:
- guaranteed delivery tomorrow
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

SOP_DOMAINS = (
    "logistics_policy",
    "after_sales_evidence",
    "promotion_policy",
    "redline_escalation",
    "sensitive_user_safety",
)


def test_provider_loads_markdown_and_filters_by_shop_and_domain(tmp_path: Path):
    path = tmp_path / "sop.md"
    path.write_text(NORMAL_MARKDOWN, encoding="utf-8")

    provider = SOPProvider.from_markdown_file(path)
    records = provider.get_records("synthetic-shop-1", "logistics_policy")

    assert provider.get_error_summary() == []
    assert len(records) == 1
    assert records[0].kb_item_id == "sop-logistics-001"
    assert records[0].shop_id == "synthetic-shop-1"
    assert records[0].domain == "logistics_policy"
    assert records[0].version == "sop-test-v1"
    assert len(records[0].content_hash) == 64


def test_provider_loads_acceptance_fixture_for_all_synthetic_shop_domains():
    provider = SOPProvider.from_markdown_file(ACCEPTANCE_SOP_FIXTURE)

    assert provider.get_error_summary() == []
    for domain in SOP_DOMAINS:
        records = provider.get_records("synthetic-shop-1", domain)

        assert len(records) == 1
        assert records[0].shop_id == "synthetic-shop-1"
        assert records[0].domain == domain
        assert records[0].version == "sop-test-v1"
        assert len(records[0].content_hash) == 64

    assert provider.get_records("another-shop", "logistics_policy") == []


@pytest.mark.parametrize("domain", SOP_DOMAINS)
def test_provider_gets_each_synthetic_shop_domain(tmp_path: Path, domain: str):
    path = tmp_path / "sop.md"
    path.write_text(NORMAL_MARKDOWN, encoding="utf-8")

    provider = SOPProvider.from_markdown_file(path)
    records = provider.get_records("synthetic-shop-1", domain)

    assert len(records) == 1
    assert records[0].shop_id == "synthetic-shop-1"
    assert records[0].domain == domain
    assert records[0].version == "sop-test-v1"
    assert len(records[0].content_hash) == 64


def test_provider_shop_id_filter_excludes_other_shops(tmp_path: Path):
    path = tmp_path / "sop.md"
    path.write_text(NORMAL_MARKDOWN, encoding="utf-8")

    provider = SOPProvider.from_markdown_file(path)

    assert provider.get_records("another-shop", "logistics_policy") == []
    assert any(error.message == "no SOP records for shop/domain" for error in provider.get_error_summary())


def test_provider_domain_filter_returns_only_requested_domain(tmp_path: Path):
    path = tmp_path / "sop.md"
    path.write_text(NORMAL_MARKDOWN, encoding="utf-8")

    provider = SOPProvider.from_markdown_file(path)
    records = provider.get_records("synthetic-shop-1", "after_sales_evidence")

    assert [record.domain for record in records] == ["after_sales_evidence"]
    assert [record.kb_item_id for record in records] == ["sop-after-sales-001"]


def test_provider_missing_file_returns_empty_and_error_summary(tmp_path: Path):
    provider = SOPProvider.from_markdown_file(tmp_path / "missing.md")

    assert provider.get_records("synthetic-shop-1", "logistics_policy") == []
    assert provider.records == []
    assert any(error.field == "file" for error in provider.get_error_summary())
    assert any(error.message == "no SOP records for shop/domain" for error in provider.get_error_summary())


def test_provider_malformed_sop_returns_error_list(tmp_path: Path):
    path = tmp_path / "bad.md"
    path.write_text(
        """## Bad SOP
kb_item_id: sop-bad-001
domain: logistics_policy
title: Missing fields
unexpected line
""",
        encoding="utf-8",
    )

    provider = SOPProvider.from_markdown_file(path)

    assert provider.records == []
    assert provider.get_records("synthetic-shop-1", "logistics_policy") == []
    fields = {error.field for error in provider.get_error_summary()}
    assert "approved_answer" in fields
    assert "" in fields


def test_provider_content_hash_is_stable(tmp_path: Path):
    path = tmp_path / "sop.md"
    path.write_text(NORMAL_MARKDOWN, encoding="utf-8")

    first = SOPProvider.from_markdown_file(path)
    second = SOPProvider.from_markdown_file(path)

    assert first.get_records("synthetic-shop-1", "logistics_policy")[0].content_hash == second.get_records(
        "synthetic-shop-1",
        "logistics_policy",
    )[0].content_hash


def test_provider_does_not_log_full_sop_content(tmp_path: Path, caplog):
    secret_text = "SECRET_FULL_SOP_CONTENT_DO_NOT_LOG"
    path = tmp_path / "sop.md"
    path.write_text(
        f"""---
shop_id: synthetic-shop-1
version: sop-test-v1
---

## Sensitive SOP
kb_item_id: sop-sensitive-001
domain: sensitive_user_safety
title: Sensitive boundary
intent_examples:
- Can a pregnant customer use this?
approved_answer: |
  {secret_text}
forbidden_phrases:
- guaranteed safe
should_transfer_human: true
risk_level: high
""",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        provider = SOPProvider.from_markdown_file(path)
        provider.get_records("another-shop", "sensitive_user_safety")

    assert secret_text in provider.records[0].approved_answer
    assert secret_text not in caplog.text
