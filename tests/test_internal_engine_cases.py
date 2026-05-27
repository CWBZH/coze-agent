import importlib.util
from pathlib import Path


CASES_PATH = Path("scripts/acceptance/internal_engine_cases.py")


def _load_cases_module():
    spec = importlib.util.spec_from_file_location("internal_engine_cases", CASES_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_default_case_registry_has_at_least_existing_coverage():
    cases_module = _load_cases_module()

    cases = cases_module.default_cases()

    assert len(cases) >= 13


def test_default_case_registry_case_ids_are_unique():
    cases_module = _load_cases_module()

    cases = cases_module.default_cases()
    case_ids = [case.case_id for case in cases]

    assert len(case_ids) == len(set(case_ids))


def test_default_case_registry_required_fields_are_complete():
    cases_module = _load_cases_module()
    required_fields = {
        "case_id",
        "question",
        "expected_intent",
        "expected_action",
        "forbidden_phrases",
        "category",
        "priority",
    }

    for case in cases_module.default_cases():
        for field_name in required_fields:
            assert hasattr(case, field_name), f"{case.case_id} missing {field_name}"
            assert getattr(case, field_name) not in (None, ""), f"{case.case_id} empty {field_name}"
        assert isinstance(case.forbidden_phrases, tuple)


def test_case_registry_exposes_t083c_extension_filter():
    cases_module = _load_cases_module()

    t083c_cases = cases_module.default_cases(include_t083c=True)

    assert len(t083c_cases) >= len(cases_module.default_cases())


def test_sop_domain_cases_cover_required_domains_and_expect_sop_source():
    cases_module = _load_cases_module()

    cases = cases_module.sop_domain_cases()

    assert len(cases) == 10
    assert {case.category for case in cases} == {"sop_domain"}
    assert all(case.expected_knowledge_source == "sop" for case in cases)
    assert all(case.expected_sop_domain for case in cases)
    assert {
        "logistics_policy",
        "after_sales_evidence",
        "promotion_policy",
        "redline_escalation",
        "sensitive_user_safety",
    } <= {case.expected_sop_domain for case in cases}


def test_sop_domain_cases_are_not_part_of_existing_default_baseline():
    cases_module = _load_cases_module()

    cases = cases_module.default_cases()

    assert len(cases) == 13
    assert all(case.category != "sop_domain" for case in cases)
