from Channel.pinduoduo.product_parser import parse_product_detail, parse_product_list


def test_product_manager_parses_realistic_goods_list_shapes():
    parsed = parse_product_list(
        {
            "success": True,
            "result": {
                "goodsList": [
                    {
                        "goodsID": 123456789,
                        "goodsName": "Test Product",
                        "hdThumbUrl": "https://example.invalid/thumb.jpg",
                        "groupPrice": 1990,
                        "salesTip": "sold 10",
                        "quantity": 8,
                        "goodsTag": {"marketingTags": ["618"]},
                    }
                ],
                "totalCount": 1,
            },
        }
    )

    assert parsed["total"] == 1
    assert parsed["products"][0]["goods_id"] == "123456789"
    assert parsed["products"][0]["goods_name"] == "Test Product"
    assert parsed["products"][0]["price"] == "19.90"
    assert parsed["products"][0]["thumb_url"] == "https://example.invalid/thumb.jpg"
    assert parsed["products"][0]["raw_item"]["goodsID"] == 123456789


def test_product_manager_finds_nested_goods_list_without_fixed_key():
    parsed = parse_product_list(
        {
            "success": True,
            "result": {
                "payload": {
                    "mallGoodsDtos": [
                        {
                            "goodsId": 565617001,
                            "goodsName": "Nested Product",
                            "thumbUrl": "https://example.invalid/nested.jpg",
                            "minOnSaleGroupPrice": 8800,
                            "maxOnSaleGroupPrice": 9900,
                        }
                    ]
                },
                "total": 1,
            },
        }
    )

    assert parsed["total"] == 1
    assert parsed["products"][0]["goods_id"] == "565617001"
    assert parsed["products"][0]["goods_name"] == "Nested Product"
    assert parsed["products"][0]["price"] == "88.00-99.00"


def test_product_manager_parses_realistic_detail_shapes():
    parsed = parse_product_detail(
        {
            "success": True,
            "result": {
                "goodsId": 123456789,
                "goodsName": "Test Product",
                "skuList": [
                    {
                        "specs": [
                            {"parentSpecName": "Size", "specName": "100ml"},
                            {"parentSpecName": "Color", "specName": "White"},
                        ]
                    }
                ],
                "cats": ["Personal care", "Face care"],
                "usageMethod": "Use once daily",
                "goodsCommitInfo": {"shelfLife": "3 years"},
            },
        }
    )

    assert parsed["goods_id"] == "123456789"
    assert parsed["goods_name"] == "Test Product"
    assert "Size: 100ml | Color: White" in parsed["specifications"]
    assert parsed["usage"] == "Use once daily"
    assert parsed["shelf_life"] == "3 years"
