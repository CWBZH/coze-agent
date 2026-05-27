"""Synthetic retrieval-only QA cases for internal RAG.

Cases contain only synthetic buyer-style questions and expected metadata. They
do not evaluate natural-language answer quality.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_SHOP_ID = "synthetic-shop-1"
DEFAULT_VERSION = "sop-test-v1"
DEFAULT_SOURCE_TYPE = "sop"

ALLOWED_DOMAINS = frozenset(
    {
        "logistics_policy",
        "after_sales_evidence",
        "promotion_policy",
        "redline_escalation",
        "sensitive_user_safety",
    }
)


@dataclass(frozen=True)
class RAGRetrievalQACase:
    case_id: str
    query: str
    shop_id: str
    domain: str
    expected_version: str
    expected_source_type: str
    expected_min_hits: int
    forbidden_domains: tuple[str, ...]
    priority: str
    category: str
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["forbidden_domains"] = list(self.forbidden_domains)
        return payload


def load_cases() -> list[RAGRetrievalQACase]:
    rows = [
        ("rag-logistics-001", "为什么还没到", "logistics_policy"),
        ("rag-logistics-002", "什么时候发货", "logistics_policy"),
        ("rag-logistics-003", "用什么快递", "logistics_policy"),
        ("rag-logistics-004", "能保证明天到吗", "logistics_policy"),
        ("rag-after-sales-001", "收到破损了", "after_sales_evidence"),
        ("rag-after-sales-002", "少发了怎么办", "after_sales_evidence"),
        ("rag-after-sales-003", "发错货了", "after_sales_evidence"),
        ("rag-after-sales-004", "漏液了", "after_sales_evidence"),
        ("rag-promotion-001", "能不能便宜点", "promotion_policy"),
        ("rag-promotion-002", "有没有赠品", "promotion_policy"),
        ("rag-promotion-003", "能返差价吗", "promotion_policy"),
        ("rag-promotion-004", "优惠券哪里领", "promotion_policy"),
        ("rag-redline-001", "你们是假货吧", "redline_escalation"),
        ("rag-redline-002", "我要投诉", "redline_escalation"),
        ("rag-redline-003", "我要找12315", "redline_escalation"),
        ("rag-redline-004", "你们赔偿吗", "redline_escalation"),
        ("rag-sensitive-001", "孕妇能用吗", "sensitive_user_safety"),
        ("rag-sensitive-002", "小孩能用吗", "sensitive_user_safety"),
        ("rag-sensitive-003", "过敏可以用吗", "sensitive_user_safety"),
        ("rag-sensitive-004", "敏感肌能用吗", "sensitive_user_safety"),
    ]
    return [_case(case_id, query, domain) for case_id, query, domain in rows]


def validate_cases(cases: list[RAGRetrievalQACase] | None = None) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for case in cases or load_cases():
        if not case.case_id:
            errors.append("case_id is required")
        if case.case_id in seen:
            errors.append(f"duplicate case_id:{case.case_id}")
        seen.add(case.case_id)
        if case.domain not in ALLOWED_DOMAINS:
            errors.append(f"{case.case_id}: invalid domain")
        if not case.expected_version:
            errors.append(f"{case.case_id}: expected_version is required")
        if case.domain in set(case.forbidden_domains):
            errors.append(f"{case.case_id}: forbidden_domains contains expected domain")
    return errors


def _case(case_id: str, query: str, domain: str) -> RAGRetrievalQACase:
    return RAGRetrievalQACase(
        case_id=case_id,
        query=query,
        shop_id=DEFAULT_SHOP_ID,
        domain=domain,
        expected_version=DEFAULT_VERSION,
        expected_source_type=DEFAULT_SOURCE_TYPE,
        expected_min_hits=1,
        forbidden_domains=tuple(sorted(ALLOWED_DOMAINS - {domain})),
        priority="P0",
        category="rag_retrieval",
    )
