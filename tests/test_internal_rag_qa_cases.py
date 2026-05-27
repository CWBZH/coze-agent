from scripts.acceptance.internal_rag_qa_cases import ALLOWED_DOMAINS, load_cases, validate_cases


def test_rag_qa_case_registry_is_complete_and_valid():
    cases = load_cases()

    assert len(cases) >= 20
    assert validate_cases(cases) == []
    assert len({case.case_id for case in cases}) == len(cases)
    assert {case.domain for case in cases} == ALLOWED_DOMAINS
    assert all(case.shop_id == "synthetic-shop-1" for case in cases)
    assert all(case.expected_version == "sop-test-v1" for case in cases)
    assert all(case.domain not in set(case.forbidden_domains) for case in cases)
