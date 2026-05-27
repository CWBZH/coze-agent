from collections import Counter

from scripts.acceptance.internal_answer_quality_cases import ALLOWED_DOMAINS, PRODUCT_VERSION, load_cases, validate_cases


def test_answer_quality_cases_are_valid_and_cover_domains():
    cases = load_cases()

    assert len(cases) >= 30
    assert validate_cases(cases) == []
    assert len({case.case_id for case in cases}) == len(cases)

    counts = Counter(case.domain for case in cases)
    for domain in ALLOWED_DOMAINS:
        assert counts[domain] >= 5


def test_policy_sensitive_cases_have_forbidden_phrases():
    cases = load_cases()

    for case in cases:
        if case.domain in {"after_sales_evidence", "promotion_policy", "redline_escalation"}:
            assert case.forbidden_phrases
        assert case.shop_id == "synthetic-shop-1"
        if case.domain == "product_catalog":
            assert case.expected_version == PRODUCT_VERSION
            assert case.expected_source_type == "product"
        else:
            assert case.expected_version == "sop-test-v1"
            assert case.expected_source_type == "sop"
        assert "真实" not in case.message


def test_sensitive_cases_allow_guardrail_block_or_transfer():
    cases = [case for case in load_cases() if case.domain == "sensitive_user_safety"]

    assert cases
    for case in cases:
        assert "transfer_human" in case.allowed_actions
        assert "blocked" in case.allowed_guardrail_statuses
