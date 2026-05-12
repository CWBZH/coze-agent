"""Tests for V3 Product Context Adapter."""

import pytest

from src.v3_product_context import ProductContextAdapter, ProductContextResult


class TestProductContextAdapter:
    """Test suite for ProductContextAdapter."""

    def test_attribute_json_dict(self):
        """Test 1: attribute_json is dict."""
        adapter = ProductContextAdapter()
        result = adapter.adapt({
            "attribute_json": {
                "category": "护肤",
                "brand": "品牌A",
                "sku_options": ["选项1", "选项2"],
            }
        })

        assert result.category == "护肤"
        assert result.brand == "品牌A"
        assert result.sku_options == ["选项1", "选项2"]

    def test_attribute_json_json_string(self):
        """Test 2: attribute_json is JSON string."""
        adapter = ProductContextAdapter()
        result = adapter.adapt({
            "attribute_json": '{"category": "护肤", "brand": "品牌A"}'
        })

        assert result.category == "护肤"
        assert result.brand == "品牌A"

    def test_attribute_json_empty_string(self):
        """Test 3: attribute_json is empty string."""
        adapter = ProductContextAdapter()
        result = adapter.adapt({"attribute_json": ""})

        assert result.category == ""
        assert result.brand == ""

    def test_attribute_json_none(self):
        """Test 4: attribute_json is None."""
        adapter = ProductContextAdapter()
        result = adapter.adapt({"attribute_json": None})

        assert result.category == ""
        assert result.brand == ""

    def test_attribute_json_invalid_json(self):
        """Test 5: attribute_json is invalid JSON string."""
        adapter = ProductContextAdapter()
        result = adapter.adapt({"attribute_json": "not valid json"})

        assert result.category == ""
        assert result.brand == ""

    def test_top_level_override(self):
        """Test 6: Top-level goods_id/goods_name/price override attr."""
        adapter = ProductContextAdapter()
        result = adapter.adapt({
            "goods_id": "top-123",
            "goods_name": "顶层商品",
            "price": "99.00",
            "attribute_json": {
                "goods_id": "attr-456",
                "goods_name": "属性商品",
                "price": "199.00",
            }
        })

        assert result.goods_id == "top-123"
        assert result.goods_name == "顶层商品"
        assert result.price == "99.00"

    def test_attr_values_override_empty_top_level(self):
        """Test 7: Attr values override empty top-level fields."""
        adapter = ProductContextAdapter()
        result = adapter.adapt({
            "goods_id": "",
            "goods_name": "   ",
            "price": "",
            "attribute_json": {
                "goods_id": "attr-789",
                "goods_name": "属性商品名",
                "price": "299.00",
            }
        })

        assert result.goods_id == "attr-789"
        assert result.goods_name == "属性商品名"
        assert result.price == "299.00"

    def test_string_fields_default_empty(self):
        """Test 8: String fields default to empty string."""
        adapter = ProductContextAdapter()
        result = adapter.adapt({})

        assert result.goods_name == ""
        assert result.category == ""
        assert result.brand == ""
        assert result.price == ""
        assert result.sku_summary == ""
        assert result.fragrance == ""
        assert result.ingredients == ""
        assert result.usage_method == ""
        assert result.usage_duration == ""
        assert result.suitable_age == ""
        assert result.skin_type == ""
        assert result.foaming == ""
        assert result.shelf_life == ""

    def test_list_fields_default_empty(self):
        """Test 9: List fields default to empty list."""
        adapter = ProductContextAdapter()
        result = adapter.adapt({})

        assert result.sku_options == []
        assert result.effect == []
        assert result.warnings == []
        assert result.accessories == []

    def test_mixed_attribute_json_types(self):
        """Test 10: Mixed valid/invalid attribute_json types."""
        adapter = ProductContextAdapter()

        # Valid dict
        result1 = adapter.adapt({"attribute_json": {"brand": "A"}})
        assert result1.brand == "A"

        # Invalid JSON string
        result2 = adapter.adapt({"attribute_json": "invalid"})
        assert result2.brand == ""

        # None
        result3 = adapter.adapt({"attribute_json": None})
        assert result3.brand == ""

    def test_goods_id_none_default(self):
        """Test 11: goods_id None default."""
        adapter = ProductContextAdapter()
        result = adapter.adapt({})

        assert result.goods_id is None

    def test_multiple_list_fields(self):
        """Test 12: Multiple list fields."""
        adapter = ProductContextAdapter()
        result = adapter.adapt({
            "attribute_json": {
                "sku_options": ["选项1", "选项2"],
                "effect": ["效果1", "效果2", "效果3"],
                "warnings": ["警告1"],
                "accessories": [],
            }
        })

        assert result.sku_options == ["选项1", "选项2"]
        assert result.effect == ["效果1", "效果2", "效果3"]
        assert result.warnings == ["警告1"]
        assert result.accessories == []

    def test_whitespace_handling_in_merge(self):
        """Test 13: Whitespace handling in merge."""
        adapter = ProductContextAdapter()
        result = adapter.adapt({
            "goods_name": "  顶层商品  ",
            "price": "  99.00  ",
            "attribute_json": {
                "goods_name": "  属性商品  ",
                "price": "  199.00  ",
            }
        })

        # Top-level fields with whitespace are considered non-empty
        assert result.goods_name == "  顶层商品  "
        assert result.price == "  99.00  "

    def test_full_integration_all_fields(self):
        """Test 14: Full integration with all 18 fields."""
        adapter = ProductContextAdapter()
        result = adapter.adapt({
            "goods_id": "12345",
            "goods_name": "测试商品",
            "price": "188.00",
            "attribute_json": {
                "category": "护肤",
                "brand": "测试品牌",
                "sku_summary": "套装",
                "sku_options": ["50ml", "100ml"],
                "fragrance": "清香",
                "effect": ["保湿", "美白"],
                "ingredients": "水,甘油",
                "usage_method": "早晚使用",
                "usage_duration": "28天",
                "suitable_age": "20-40岁",
                "skin_type": "干性",
                "foaming": "是",
                "shelf_life": "3年",
                "warnings": ["请勿接触眼睛"],
                "accessories": ["赠送小样"],
            }
        })

        # Top-level fields
        assert result.goods_id == "12345"
        assert result.goods_name == "测试商品"
        assert result.price == "188.00"

        # Attribute fields
        assert result.category == "护肤"
        assert result.brand == "测试品牌"
        assert result.sku_summary == "套装"
        assert result.sku_options == ["50ml", "100ml"]
        assert result.fragrance == "清香"
        assert result.effect == ["保湿", "美白"]
        assert result.ingredients == "水,甘油"
        assert result.usage_method == "早晚使用"
        assert result.usage_duration == "28天"
        assert result.suitable_age == "20-40岁"
        assert result.skin_type == "干性"
        assert result.foaming == "是"
        assert result.shelf_life == "3年"
        assert result.warnings == ["请勿接触眼睛"]
        assert result.accessories == ["赠送小样"]

    def test_result_is_dataclass(self):
        """Test that result is a proper dataclass instance."""
        adapter = ProductContextAdapter()
        result = adapter.adapt({})

        assert isinstance(result, ProductContextResult)
        assert hasattr(result, "goods_id")
        assert hasattr(result, "goods_name")
        assert hasattr(result, "__dataclass_fields__")
