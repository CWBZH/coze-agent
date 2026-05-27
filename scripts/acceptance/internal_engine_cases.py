"""Reusable synthetic case registry for InternalWorkflowEngine acceptance QA.

The registry is intentionally synthetic-only. Cases contain deterministic
questions and expectations, but never real buyer identifiers or production
conversation text.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


SYNTHETIC_GOODS_NAME = "Synthetic Rose Water"


def load_sop_fixture_summary(sop_file: str | Path | None) -> dict[str, Any]:
    if not sop_file:
        return _empty_sop_summary()

    from Message.workflow.sop_loader import load_sop_markdown

    result = load_sop_markdown(Path(sop_file))
    domains = sorted({record.domain for record in result.records if str(record.domain or "").strip()})
    versions = sorted({record.version for record in result.records if str(record.version or "").strip()})
    metadata_version = str(result.metadata.get("version") or "").strip()
    version = metadata_version or (versions[0] if len(versions) == 1 else "")
    return {
        "sop_record_count": len(result.records),
        "sop_domains": domains,
        "sop_version": version,
        "sop_error_count": len(result.errors),
    }


def _empty_sop_summary() -> dict[str, Any]:
    return {
        "sop_record_count": 0,
        "sop_domains": [],
        "sop_version": "",
        "sop_error_count": 0,
    }


class SyntheticCase:
    def __init__(
        self,
        *,
        case_id: str,
        question: str | None = None,
        content: str | None = None,
        expected_intent: str,
        expected_action: str,
        forbidden_phrases: tuple[str, ...] = (),
        category: str,
        priority: str = "P1",
        required: bool = True,
        goods_context: dict[str, Any] | None = None,
        shop_id: str = "synthetic-shop-1",
        expected_reason: str = "",
        expect_reply: bool | None = None,
        expect_knowledge_refs: bool | None = None,
        expected_knowledge_source: str = "",
        expected_sop_domain: str = "",
    ):
        resolved_question = question if question is not None else content
        if not resolved_question:
            raise ValueError("SyntheticCase requires question or content")

        self.case_id = case_id
        self.question = resolved_question
        self.content = resolved_question
        self.expected_intent = expected_intent
        self.expected_action = expected_action
        self.forbidden_phrases = forbidden_phrases
        self.category = category
        self.priority = priority
        self.required = required
        self.goods_context = goods_context
        self.shop_id = shop_id
        self.expected_reason = expected_reason
        self.expect_reply = expect_reply
        self.expect_knowledge_refs = expect_knowledge_refs
        self.expected_knowledge_source = expected_knowledge_source
        self.expected_sop_domain = expected_sop_domain


def synthetic_product_records() -> list[dict[str, Any]]:
    return [
        {
            "shop_id": "synthetic-shop-1",
            "domain": "product_catalog",
            "source": "synthetic_product_record",
            "goods_id": "synthetic-rose-water",
            "goods_name": SYNTHETIC_GOODS_NAME,
            "price": "synthetic-price-99",
            "specifications": "synthetic-spec-100ml",
            "usage_method": "synthetic-usage-method",
            "ingredients": "synthetic-ingredient-list",
            "shelf_life": "synthetic-shelf-life",
            "warnings": "synthetic-warning-text",
            "manual_notes": "synthetic record only; page display is authoritative",
        }
    ]


def default_cases(*, include_t083c: bool = False) -> list[SyntheticCase]:
    import Session.session_manager  # Import order avoids existing core/logger circular import.
    from Message.workflow.internal_engine import InternalWorkflowEngine

    engine_rules = InternalWorkflowEngine
    cases = [
        SyntheticCase(
            case_id="T100G-P0-001",
            category="redline",
            priority="P0",
            question=engine_rules._REDLINE_KEYWORDS[3],
            expected_action="transfer_human",
            expected_intent="human_escalation_redline",
            forbidden_phrases=(),
            expected_reason="redline_requires_human",
            expect_reply=False,
        ),
        SyntheticCase(
            case_id="T100G-P0-002",
            category="explicit-human",
            priority="P0",
            question=engine_rules._EXPLICIT_HUMAN_KEYWORDS[0],
            expected_action="transfer_human",
            expected_intent="explicit_human_request",
            forbidden_phrases=(),
            expected_reason="buyer_requested_human",
            expect_reply=False,
        ),
        SyntheticCase(
            case_id="T100G-P0-003",
            category="after-sales",
            priority="P0",
            question=engine_rules._EVIDENCE_KEYWORDS[0],
            expected_action="request_evidence",
            expected_intent="after_sales_evidence_collection",
            forbidden_phrases=(),
            expected_reason="request_buyer_evidence",
            expect_reply=True,
        ),
        SyntheticCase(
            case_id="T100G-P0-004",
            category="logistics",
            priority="P0",
            question=engine_rules._LOGISTICS_KEYWORDS[0],
            expected_action="reply",
            expected_intent="logistics_order_status",
            forbidden_phrases=(),
            expect_reply=True,
        ),
        SyntheticCase(
            case_id="T100G-P0-005",
            category="promotion",
            priority="P0",
            question=engine_rules._PROMOTION_KEYWORDS[0],
            expected_action="reply",
            expected_intent="promotion_policy",
            forbidden_phrases=(),
            expect_reply=True,
        ),
        SyntheticCase(
            case_id="T100G-P0-006",
            category="sensitive-user",
            priority="P0",
            question=engine_rules._SENSITIVE_USER_KEYWORDS[0],
            expected_action="reply",
            expected_intent="sensitive_user_safety",
            forbidden_phrases=(),
            expect_reply=True,
            expect_knowledge_refs=False,
        ),
        SyntheticCase(
            case_id="T100G-P1-007",
            category="product-price",
            priority="P1",
            question=engine_rules._PRODUCT_BASIC_KEYWORDS[0],
            goods_context={"goods_name": SYNTHETIC_GOODS_NAME},
            expected_action="reply",
            expected_intent="product_basic",
            forbidden_phrases=(),
            expected_reason="product_knowledge_found",
            expect_reply=True,
            expect_knowledge_refs=True,
        ),
        SyntheticCase(
            case_id="T100G-P1-008",
            category="product-ingredients",
            priority="P1",
            question=f"{SYNTHETIC_GOODS_NAME} {engine_rules._PRODUCT_BASIC_KEYWORDS[4]}",
            expected_action="reply",
            expected_intent="product_basic",
            forbidden_phrases=(),
            expected_reason="product_knowledge_found",
            expect_reply=True,
            expect_knowledge_refs=True,
        ),
        SyntheticCase(
            case_id="T100G-P1-009",
            category="product-usage",
            priority="P1",
            question=f"{SYNTHETIC_GOODS_NAME} {engine_rules._PRODUCT_BASIC_KEYWORDS[3]}",
            expected_action="reply",
            expected_intent="product_basic",
            forbidden_phrases=(),
            expected_reason="product_knowledge_found",
            expect_reply=True,
            expect_knowledge_refs=True,
        ),
        SyntheticCase(
            case_id="T100G-P1-010",
            category="product-shelf-life",
            priority="P1",
            question=f"{SYNTHETIC_GOODS_NAME} {engine_rules._PRODUCT_BASIC_KEYWORDS[5]}",
            expected_action="reply",
            expected_intent="product_basic",
            forbidden_phrases=(),
            expected_reason="product_knowledge_found",
            expect_reply=True,
            expect_knowledge_refs=True,
        ),
        SyntheticCase(
            case_id="T100G-P1-011",
            category="product-specification",
            priority="P1",
            question=f"{SYNTHETIC_GOODS_NAME} {engine_rules._PRODUCT_BASIC_KEYWORDS[2]}",
            expected_action="reply",
            expected_intent="product_basic",
            forbidden_phrases=(),
            expected_reason="product_knowledge_found",
            expect_reply=True,
            expect_knowledge_refs=True,
        ),
        SyntheticCase(
            case_id="T100G-P1-012",
            category="product-suitability",
            priority="P1",
            question=f"{SYNTHETIC_GOODS_NAME} {engine_rules._PRODUCT_BASIC_KEYWORDS[6]}",
            expected_action="reply",
            expected_intent="product_basic",
            forbidden_phrases=(),
            expected_reason="product_knowledge_found",
            expect_reply=True,
            expect_knowledge_refs=True,
        ),
        SyntheticCase(
            case_id="T100G-P1-013",
            category="fallback",
            priority="P1",
            question="synthetic unmatched customer question",
            expected_action="fallback",
            expected_intent="fallback",
            forbidden_phrases=(),
            expected_reason="no_rule_matched",
            expect_reply=False,
            expect_knowledge_refs=False,
        ),
    ]

    if include_t083c:
        return cases + t083c_cases()
    return cases


def t083c_cases() -> list[SyntheticCase]:
    return []


def sop_domain_cases() -> list[SyntheticCase]:
    import Session.session_manager  # Import order avoids existing core/logger circular import.
    from Message.workflow.internal_engine import InternalWorkflowEngine

    engine_rules = InternalWorkflowEngine
    shop_id = "synthetic-shop-1"
    common = {
        "category": "sop_domain",
        "priority": "P0",
        "shop_id": shop_id,
        "expected_knowledge_source": "sop",
        "expect_reply": True,
        "expect_knowledge_refs": True,
    }
    return [
        SyntheticCase(
            case_id="T101G-SOP-001",
            question=engine_rules._LOGISTICS_KEYWORDS[0],
            expected_action="reply",
            expected_intent="logistics_order_status",
            expected_reason="logistics_policy_order_page_boundary",
            expected_sop_domain="logistics_policy",
            **common,
        ),
        SyntheticCase(
            case_id="T101G-SOP-002",
            question=engine_rules._EVIDENCE_KEYWORDS[0],
            expected_action="request_evidence",
            expected_intent="after_sales_evidence_collection",
            expected_reason="request_buyer_evidence",
            expected_sop_domain="after_sales_evidence",
            **common,
        ),
        SyntheticCase(
            case_id="T101G-SOP-003",
            question=engine_rules._EVIDENCE_KEYWORDS[4],
            expected_action="request_evidence",
            expected_intent="after_sales_evidence_collection",
            expected_reason="request_buyer_evidence",
            expected_sop_domain="after_sales_evidence",
            **common,
        ),
        SyntheticCase(
            case_id="T101G-SOP-004",
            question=engine_rules._PROMOTION_KEYWORDS[0],
            expected_action="reply",
            expected_intent="promotion_policy",
            expected_reason="promotion_policy_page_or_checkout_boundary",
            expected_sop_domain="promotion_policy",
            **common,
        ),
        SyntheticCase(
            case_id="T101G-SOP-005",
            question=engine_rules._REDLINE_KEYWORDS[0],
            expected_action="transfer_human",
            expected_intent="human_escalation_redline",
            expected_reason="redline_requires_human_review",
            expected_sop_domain="redline_escalation",
            **common,
        ),
        SyntheticCase(
            case_id="T101G-SOP-006",
            question=engine_rules._REDLINE_KEYWORDS[3],
            expected_action="transfer_human",
            expected_intent="human_escalation_redline",
            expected_reason="redline_requires_human_review",
            expected_sop_domain="redline_escalation",
            **common,
        ),
        SyntheticCase(
            case_id="T101G-SOP-007",
            question=engine_rules._REDLINE_KEYWORDS[5],
            expected_action="transfer_human",
            expected_intent="human_escalation_redline",
            expected_reason="redline_requires_human_review",
            expected_sop_domain="redline_escalation",
            **common,
        ),
        SyntheticCase(
            case_id="T101G-SOP-008",
            question=engine_rules._SENSITIVE_USER_KEYWORDS[0],
            expected_action="reply",
            expected_intent="sensitive_user_safety",
            expected_reason="sensitive_safety_conservative_boundary",
            expected_sop_domain="sensitive_user_safety",
            **common,
        ),
        SyntheticCase(
            case_id="T101G-SOP-009",
            question=engine_rules._SENSITIVE_USER_KEYWORDS[3],
            expected_action="reply",
            expected_intent="sensitive_user_safety",
            expected_reason="sensitive_safety_conservative_boundary",
            expected_sop_domain="sensitive_user_safety",
            **common,
        ),
        SyntheticCase(
            case_id="T101G-SOP-010",
            question=engine_rules._SENSITIVE_USER_KEYWORDS[1],
            expected_action="reply",
            expected_intent="sensitive_user_safety",
            expected_reason="sensitive_safety_conservative_boundary",
            expected_sop_domain="sensitive_user_safety",
            **common,
        ),
    ]
