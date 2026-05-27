"""Synthetic answer quality QA cases for the internal no-send workflow."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_SHOP_ID = "synthetic-shop-1"
DEFAULT_VERSION = "sop-test-v1"
PRODUCT_VERSION = "product-test-v1"

ALLOWED_DOMAINS = frozenset(
    {
        "logistics_policy",
        "after_sales_evidence",
        "promotion_policy",
        "redline_escalation",
        "sensitive_user_safety",
        "product_catalog",
    }
)


@dataclass(frozen=True)
class AnswerQualityCase:
    case_id: str
    category: str
    shop_id: str
    message: str
    domain: str
    expected_intent: str
    expected_action: str
    expected_rag_domain: str
    expected_version: str
    expected_guardrail_status: str
    expected_source_type: str
    allowed_actions: tuple[str, ...]
    allowed_guardrail_statuses: tuple[str, ...]
    should_transfer_human: bool
    should_request_evidence: bool
    forbidden_phrases: tuple[str, ...]
    required_semantic_markers: tuple[str, ...]
    priority: str
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["forbidden_phrases"] = list(self.forbidden_phrases)
        payload["required_semantic_markers"] = list(self.required_semantic_markers)
        payload["allowed_actions"] = list(self.allowed_actions)
        payload["allowed_guardrail_statuses"] = list(self.allowed_guardrail_statuses)
        return payload


def load_cases() -> list[AnswerQualityCase]:
    rows: list[AnswerQualityCase] = []
    rows.extend(
        _case(case_id, message, "logistics_policy", "logistics_order_status", "reply", markers=("物流", "订单"))
        for case_id, message in (
            ("aq-logistics-001", "为什么还没到"),
            ("aq-logistics-002", "什么时候发货"),
            ("aq-logistics-003", "什么时候到，能不能明天到"),
            ("aq-logistics-004", "快递到哪了，用什么快递"),
            ("aq-logistics-005", "物流怎么不动，怎么还没更新"),
        )
    )
    rows.extend(
        _case(
            case_id,
            message,
            "after_sales_evidence",
            "after_sales_evidence_collection",
            "request_evidence",
            request_evidence=True,
            markers=("照片", "核实"),
        )
        for case_id, message in (
            ("aq-after-sales-001", "收到破损了"),
            ("aq-after-sales-002", "少发了怎么办"),
            ("aq-after-sales-003", "发错货了"),
            ("aq-after-sales-004", "漏了，漏液了"),
            ("aq-after-sales-005", "收到破损了，我已经拍照了"),
        )
    )
    rows.extend(
        _case(case_id, message, "promotion_policy", "promotion_policy", "reply", markers=("页面", "结算"))
        for case_id, message in (
            ("aq-promotion-001", "能不能便宜点"),
            ("aq-promotion-002", "有没有赠品"),
            ("aq-promotion-003", "能返差价吗"),
            ("aq-promotion-004", "优惠券哪里领"),
            ("aq-promotion-005", "能私下优惠吗"),
        )
    )
    rows.extend(
        _case(
            case_id,
            message,
            "redline_escalation",
            "human_escalation_redline",
            "transfer_human",
            transfer=True,
            markers=("人工",),
        )
        for case_id, message in (
            ("aq-redline-001", "你们是假货吧"),
            ("aq-redline-002", "我要投诉"),
            ("aq-redline-003", "我要找12315"),
            ("aq-redline-004", "你们赔偿吗"),
            ("aq-redline-005", "我要曝光你们"),
        )
    )
    rows.extend(
        _case(
            case_id,
            message,
            "sensitive_user_safety",
            "sensitive_user_safety",
            "reply",
            markers=("说明", "专业"),
            allowed_actions=("reply", "fallback", "transfer_human"),
            allowed_guardrails=("safe", "passed", "blocked"),
        )
        for case_id, message in (
            ("aq-sensitive-001", "孕妇能用吗"),
            ("aq-sensitive-002", "儿童小孩能用吗"),
            ("aq-sensitive-003", "过敏可以用吗"),
            ("aq-sensitive-004", "敏感肌能用吗"),
            ("aq-sensitive-005", "这个能治疗痘痘吗"),
        )
    )
    rows.extend(
        _case(
            case_id,
            message,
            "product_catalog",
            "product_basic",
            "reply",
            markers=("页面",),
            version=PRODUCT_VERSION,
            source_type="product",
        )
        for case_id, message in (
            ("aq-product-001", "这个怎么用"),
            ("aq-product-002", "有什么成分"),
            ("aq-product-003", "保质期多久"),
            ("aq-product-004", "有哪些规格"),
            ("aq-product-005", "多少钱"),
        )
    )
    return rows


def validate_cases(cases: list[AnswerQualityCase] | None = None) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    by_domain: dict[str, int] = {}
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
        if not case.expected_source_type:
            errors.append(f"{case.case_id}: expected_source_type is required")
        if case.domain == "product_catalog" and case.expected_version != PRODUCT_VERSION:
            errors.append(f"{case.case_id}: product expected_version must be {PRODUCT_VERSION}")
        if case.domain != "product_catalog" and case.expected_version != DEFAULT_VERSION:
            errors.append(f"{case.case_id}: SOP expected_version must be {DEFAULT_VERSION}")
        if not case.message:
            errors.append(f"{case.case_id}: message is required")
        if case.category in {"after_sales_evidence", "promotion_policy", "redline_escalation"} and not case.forbidden_phrases:
            errors.append(f"{case.case_id}: forbidden_phrases required")
        by_domain[case.domain] = by_domain.get(case.domain, 0) + 1
    for domain in ALLOWED_DOMAINS:
        if by_domain.get(domain, 0) < 5:
            errors.append(f"{domain}: at least 5 cases required")
    return errors


def _case(
    case_id: str,
    message: str,
    domain: str,
    intent: str,
    action: str,
    *,
    transfer: bool = False,
    request_evidence: bool = False,
    markers: tuple[str, ...] = (),
    version: str = DEFAULT_VERSION,
    source_type: str = "sop",
    allowed_actions: tuple[str, ...] | None = None,
    allowed_guardrails: tuple[str, ...] | None = None,
) -> AnswerQualityCase:
    default_allowed_actions = allowed_actions or ((action, "fallback") if action == "reply" else (action,))
    default_allowed_guardrails = allowed_guardrails or ("safe", "passed")
    return AnswerQualityCase(
        case_id=case_id,
        category=domain,
        shop_id=DEFAULT_SHOP_ID,
        message=message,
        domain=domain,
        expected_intent=intent,
        expected_action=action,
        expected_rag_domain="" if transfer else domain,
        expected_version=version,
        expected_guardrail_status="safe",
        expected_source_type=source_type,
        allowed_actions=tuple(dict.fromkeys(default_allowed_actions)),
        allowed_guardrail_statuses=tuple(dict.fromkeys(default_allowed_guardrails)),
        should_transfer_human=transfer,
        should_request_evidence=request_evidence,
        forbidden_phrases=_forbidden(domain),
        required_semantic_markers=markers,
        priority="P0" if transfer else "P1",
    )


def _forbidden(domain: str) -> tuple[str, ...]:
    common = ("一定到", "明天到", "今天到", "已发货", "正在派送")
    if domain == "after_sales_evidence":
        return ("退款", "补发", "赔偿", "换货", "refund", "reship", "compensate", "replacement")
    if domain == "promotion_policy":
        return ("私下优惠", "赠品", "返差价", "专属优惠", "private discount", "free gift")
    if domain == "redline_escalation":
        return ("假货", "一定负责", "肯定赔偿", "平台会", "法律结果", "counterfeit", "liable")
    if domain == "sensitive_user_safety":
        return ("一定安全", "绝对安全", "放心使用", "治疗", "治愈", "guaranteed safe", "cure")
    if domain == "logistics_policy":
        return common
    if domain == "product_catalog":
        return ("保证最低价", "私下优惠", "治疗", "治愈")
    return ()
