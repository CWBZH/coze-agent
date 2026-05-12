"""Tests for V3 Product Context Adapter."""
import importlib.util
import sys
from pathlib import Path

import pytest

# Load module from Agent/CustomerAgent/custom path
module_path = Path(__file__).parent.parent / "Agent" / "CustomerAgent" / "custom" / "v3_product_context.py"
spec = importlib.util.spec_from_file_location("v3_product_context", module_path)
v3_product_context = importlib.util.module_from_spec(spec)
sys.modules["v3_product_context"] = v3_product_context
spec.loader.exec_module(v3_product_context)

ProductContextAdapter = v3_product_context.ProductContextAdapter
ProductContextResult = v3_product_context.ProductContextResult


class SimpleRecord:
    """Simple object with attributes for testing."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_1_dict_record_top_level_fields():
    """Test dict record with top-level goods_id/goods_name/price."""
    record = {
        "goods_id": "12345",
        "goods_name": "Test Product",
        "price": "99.00"
    }
    result = ProductContextAdapter.from_record(record)

    assert result.product["goods_id"] == "12345"
    assert result.product["goods_name"] == "Test Product"
    assert result.product["price"] == "99.00"
    assert len(result.warnings) == 0


def test_2_object_record_attributes():
    """Test object record with attributes."""
    record = SimpleRecord(
        goods_id="obj123",
        goods_name="Object Product",
        price="50.00"
    )
    result = ProductContextAdapter.from_record(record)

    assert result.product["goods_id"] == "obj123"
    assert result.product["goods_name"] == "Object Product"
    assert result.product["price"] == "50.00"
    assert len(result.warnings) == 0


def test_3_valid_json_string_attribute_json_merges():
    """Test valid JSON string attribute_json merges fields."""
    record = {
        "goods_id": "g1",
        "goods_name": "Base",
        "price": "10.00",
        "attribute_json": '{"category": "Skin Care", "brand": "TestBrand"}'
    }
    result = ProductContextAdapter.from_record(record)

    assert result.product["goods_id"] == "g1"
    assert result.product["goods_name"] == "Base"
    assert result.product["category"] == "Skin Care"
    assert result.product["brand"] == "TestBrand"
    assert len(result.warnings) == 0


def test_4_dict_attribute_json_merges():
    """Test dict attribute_json merges fields."""
    record = {
        "goods_id": "g2",
        "goods_name": "Base2",
        "price": "20.00",
        "attribute_json": {
            "category": "Hair Care",
            "fragrance": "Lavender"
        }
    }
    result = ProductContextAdapter.from_record(record)

    assert result.product["goods_id"] == "g2"
    assert result.product["category"] == "Hair Care"
    assert result.product["fragrance"] == "Lavender"
    assert len(result.warnings) == 0


def test_5_invalid_json_warning_and_defaults_preserved():
    """Test invalid JSON warning and defaults/top-level preserved."""
    record = {
        "goods_id": "g3",
        "goods_name": "Top",
        "price": "30.00",
        "attribute_json": "{invalid json"
    }
    result = ProductContextAdapter.from_record(record)

    assert result.product["goods_id"] == "g3"
    assert result.product["goods_name"] == "Top"
    assert result.product["price"] == "30.00"
    # Defaults should be applied
    assert result.product["category"] == ""
    assert result.product["brand"] == ""
    assert "invalid_attribute_json" in result.warnings


def test_6_attr_empty_does_not_erase_top_level():
    """Test attr empty goods_name/price does not erase top-level."""
    record = {
        "goods_id": "g4",
        "goods_name": "TopName",
        "price": "40.00",
        "attribute_json": {
            "goods_name": "",
            "price": ""
        }
    }
    result = ProductContextAdapter.from_record(record)

    assert result.product["goods_name"] == "TopName"
    assert result.product["price"] == "40.00"


def test_6b_attr_non_empty_does_not_override_top_level():
    """Test attr non-empty goods_id/goods_name/price cannot override non-empty top-level."""
    record = {
        "goods_id": "top123",
        "goods_name": "Top Product",
        "price": "100.00",
        "attribute_json": {
            "goods_id": "attr456",
            "goods_name": "Attr Product",
            "price": "200.00"
        }
    }
    result = ProductContextAdapter.from_record(record)

    # Top-level values must be preserved
    assert result.product["goods_id"] == "top123"
    assert result.product["goods_name"] == "Top Product"
    assert result.product["price"] == "100.00"


def test_7_sku_options_string_to_single_item_list():
    """Test sku_options string -> single-item list."""
    record = {
        "goods_id": "g5",
        "attribute_json": {
            "sku_options": "Red"
        }
    }
    result = ProductContextAdapter.from_record(record)

    assert result.product["sku_options"] == ["Red"]


def test_8_sku_options_list_preserves_order_and_stringifies():
    """Test sku_options list preserves order and stringifies items."""
    record = {
        "goods_id": "g6",
        "attribute_json": {
            "sku_options": ["Red", None, "Blue", 123]
        }
    }
    result = ProductContextAdapter.from_record(record)

    assert result.product["sku_options"] == ["Red", "Blue", "123"]


def test_9_effect_warnings_accessories_normalization():
    """Test effect/warnings/accessories string/list normalization."""
    # String -> list
    record1 = {
        "goods_id": "g7",
        "attribute_json": {
            "effect": "Brightening",
            "warnings": "Avoid eyes",
            "accessories": "Pump"
        }
    }
    result1 = ProductContextAdapter.from_record(record1)

    assert result1.product["effect"] == ["Brightening"]
    assert result1.product["warnings"] == ["Avoid eyes"]
    assert result1.product["accessories"] == ["Pump"]

    # List -> preserve order
    record2 = {
        "goods_id": "g8",
        "attribute_json": {
            "effect": ["A", "B"],
            "warnings": ["W1", None, "W2"],
            "accessories": []
        }
    }
    result2 = ProductContextAdapter.from_record(record2)

    assert result2.product["effect"] == ["A", "B"]
    assert result2.product["warnings"] == ["W1", "W2"]
    assert result2.product["accessories"] == []


def test_10_specifications_fallback_fills_sku_summary():
    """Test specifications fallback fills sku_summary only when missing."""
    # sku_summary missing -> use specifications
    record1 = {
        "goods_id": "g9",
        "specifications": "Special formula",
        "attribute_json": {}
    }
    result1 = ProductContextAdapter.from_record(record1)

    assert result1.product["sku_summary"] == "Special formula"

    # sku_summary present -> don't overwrite
    record2 = {
        "goods_id": "g10",
        "specifications": "Should not appear",
        "attribute_json": {
            "sku_summary": "Actual summary"
        }
    }
    result2 = ProductContextAdapter.from_record(record2)

    assert result2.product["sku_summary"] == "Actual summary"


def test_11_suitable_age_manual_annotation_preserved():
    """Test suitable_age manual annotation preserved exactly."""
    record = {
        "goods_id": "g11",
        "attribute_json": {
            "suitable_age": "12岁以上"
        }
    }
    result = ProductContextAdapter.from_record(record)

    assert result.product["suitable_age"] == "12岁以上"


def test_12_unknown_attr_fields_warning_sorted():
    """Test unknown attr fields warning sorted."""
    record = {
        "goods_id": "g12",
        "attribute_json": {
            "unknown_z": "value",
            "unknown_a": "value",
            "unknown_m": "value"
        }
    }
    result = ProductContextAdapter.from_record(record)

    assert len(result.warnings) == 1
    assert result.warnings[0] == "unknown_attribute_fields:unknown_a,unknown_m,unknown_z"


def test_13_all_18_fields_always_exist():
    """Test all 18 fields always exist."""
    record = {
        "goods_id": "g13"
    }
    result = ProductContextAdapter.from_record(record)

    expected_fields = [
        "goods_id", "goods_name", "category", "brand", "price", "sku_summary",
        "sku_options", "fragrance", "effect", "ingredients", "usage_method",
        "usage_duration", "suitable_age", "skin_type", "foaming", "shelf_life",
        "warnings", "accessories"
    ]

    for f in expected_fields:
        assert f in result.product, f"Missing field: {f}"

    assert len(result.product) == 18


def test_14_no_image_field_in_output():
    """Test no image field in output."""
    record = {
        "goods_id": "g14",
        "attribute_json": {
            "image": "http://example.com/img.jpg",
            "category": "Test"
        }
    }
    result = ProductContextAdapter.from_record(record)

    assert "image" not in result.product
    assert result.product["category"] == "Test"


def test_15_price_range_fallback_when_price_missing():
    """Test price_range fallback when price missing."""
    record = {
        "goods_id": "g15",
        "price_range": "100-200"
    }
    result = ProductContextAdapter.from_record(record)

    assert result.product["price"] == "100-200"


def test_16_attr_known_field_fills_empty_top_level():
    """Test attr known field fills empty top-level goods_name/price."""
    record = {
        "goods_id": "g16",
        "goods_name": "",
        "price": "",
        "attribute_json": {
            "goods_name": "From Attr",
            "price": "88.00"
        }
    }
    result = ProductContextAdapter.from_record(record)

    assert result.product["goods_name"] == "From Attr"
    assert result.product["price"] == "88.00"
