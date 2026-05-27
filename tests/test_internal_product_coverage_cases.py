from scripts.acceptance.internal_product_coverage_cases import build_cases_from_records


def test_build_cases_from_product_records_is_bounded_and_sanitized():
    records = [
        {
            "shop_id": "shop-a",
            "goods_id": "goods-1",
            "goods_name": "Private Product Name Should Not Appear",
            "specifications": "100ml",
            "price": "99",
            "usage_method": "Use after cleaning",
            "ingredients": "Private ingredient detail",
            "shelf_life": "24 months",
            "warnings": "Patch test first",
            "manual_notes": "Private manual notes",
            "raw_detail_json": "RAW_DETAIL_JSON_SHOULD_NOT_LEAK",
        }
    ]

    cases = build_cases_from_records(records, shop_id="shop-a", version="real-product-v1", limit=6)
    rendered = "\n".join(str(case) for case in cases)

    assert len(cases) == 6
    assert len({case.case_id for case in cases}) == len(cases)
    assert all(case.shop_id == "shop-a" for case in cases)
    assert all(case.expected_version == "real-product-v1" for case in cases)
    assert all(case.expected_domain == "product_catalog" for case in cases)
    assert all(case.expected_source_type == "product" for case in cases)
    assert "RAW_DETAIL_JSON_SHOULD_NOT_LEAK" not in rendered
    assert "Private ingredient detail" not in rendered


def test_case_limit_is_respected():
    cases = build_cases_from_records(
        [{"shop_id": "shop-a", "goods_id": "goods-1", "goods_name": "Synthetic Product", "price": "99"}],
        shop_id="shop-a",
        version="real-product-v1",
        limit=2,
    )

    assert len(cases) == 2
