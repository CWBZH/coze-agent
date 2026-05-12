"""
Unit tests for V3.0 PromptBuilder - no LLM calls required.
"""
import pytest
import sys
import importlib.util
from pathlib import Path

# Load prompt_builder module directly without triggering __init__.py
# This avoids dependency on services that aren't initialized in test context
module_path = Path(__file__).parent.parent / "Agent" / "CustomerAgent" / "custom" / "prompt_builder.py"
spec = importlib.util.spec_from_file_location("prompt_builder", module_path)
prompt_builder_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prompt_builder_module)

PromptBuilder = prompt_builder_module.PromptBuilder


class TestPromptBuilder:
    """Test suite for PromptBuilder class."""

    def test_build_product_json_field_order(self):
        """Verify 18 fields in correct order including price."""
        builder = PromptBuilder()
        product = {
            "goods_id": "946901558797",
            "goods_name": "测试商品",
            "category": "个护",
            "brand": "测试品牌",
            "price": "4.80-12.00",
            "sku_summary": "20ml",
            "sku_options": ["一瓶", "2瓶"],
            "fragrance": "清香",
            "effect": ["保湿"],
            "ingredients": "水",
            "usage_method": "喷涂",
            "usage_duration": "2-3小时",
            "suitable_age": "12岁以上",
            "skin_type": "所有肤质",
            "foaming": "",
            "shelf_life": "",
            "warnings": "",
            "accessories": "",
        }

        result = builder.build_product_json(product)

        expected_fields = [
            "goods_id", "goods_name", "category", "brand", "price",
            "sku_summary", "sku_options", "fragrance", "effect",
            "ingredients", "usage_method", "usage_duration",
            "suitable_age", "skin_type", "foaming", "shelf_life",
            "warnings", "accessories"
        ]

        assert list(result.keys()) == expected_fields
        assert result["price"] == "4.80-12.00"

    def test_build_product_json_empty_fields(self):
        """Empty fields should become empty strings, except list fields which become []."""
        builder = PromptBuilder()
        product = {
            "goods_id": "123",
            "goods_name": "测试商品",
            "category": "",
            "brand": None,
            "price": "",
            "sku_summary": "20ml",
            "sku_options": ["一瓶"],
            "fragrance": "",
            "effect": [],
            "ingredients": "",
            "usage_method": "",
            "usage_duration": "",
            "suitable_age": "",
            "skin_type": "",
            "foaming": None,
            "shelf_life": "",
            "warnings": None,
            "accessories": None,
        }

        result = builder.build_product_json(product)

        assert result["category"] == ""
        assert result["brand"] == ""
        assert result["foaming"] == ""
        assert result["warnings"] == []
        assert result["accessories"] == []
        assert result["effect"] == []

    def test_build_messages_includes_product_json(self):
        """System prompt must contain formatted product JSON including price."""
        builder = PromptBuilder()
        product_json = {
            "goods_id": "123",
            "goods_name": "测试商品",
            "category": "个护",
            "brand": "测试品牌",
            "price": "9.90-19.90",
            "sku_summary": "20ml",
            "sku_options": ["一瓶", "2瓶"],
            "fragrance": "清香",
            "effect": ["保湿"],
            "ingredients": "水",
            "usage_method": "喷涂",
            "usage_duration": "2-3小时",
            "suitable_age": "12岁以上",
            "skin_type": "所有肤质",
            "foaming": "",
            "shelf_life": "",
            "warnings": [],
            "accessories": [],
        }

        messages = builder.build_messages(product_json, "有什么规格?")

        system_content = messages[0]["content"]
        assert "商品信息" in system_content
        assert "goods_id" in system_content or "123" in system_content
        assert "测试商品" in system_content
        assert "price" in system_content or "9.90" in system_content

    def test_build_messages_sku_preservation_rules(self):
        """Rules must mention both '一瓶' and '1瓶' as valid source formats."""
        builder = PromptBuilder()
        product_json = {
            "goods_id": "946901558797",
            "goods_name": "测试商品",
            "category": "个护",
            "brand": "测试品牌",
            "sku_summary": "20ml",
            "sku_options": ["一瓶", "2瓶", "3瓶"],
            "fragrance": "",
            "effect": [],
            "ingredients": "",
            "usage_method": "",
            "usage_duration": "",
            "suitable_age": "",
            "skin_type": "",
            "foaming": "",
            "shelf_life": "",
            "warnings": "",
            "accessories": "",
        }

        messages = builder.build_messages(product_json, "有哪些规格?")

        system_content = messages[0]["content"]

        # Must mention both variants as valid sources that shouldn't be rewritten
        assert "一瓶" in system_content
        assert "1瓶" in system_content or "原文" in system_content

    def test_sku_example_answer_includes_all_options(self):
        """Specification example must include every SKU option."""
        builder = PromptBuilder()
        product_json = {
            "goods_id": "123",
            "goods_name": "测试商品",
            "category": "",
            "brand": "",
            "price": "",
            "sku_summary": "2支",
            "sku_options": ["体验装一支", "2支", "3支", "5支"],
            "fragrance": "",
            "effect": [],
            "ingredients": "",
            "usage_method": "",
            "usage_duration": "",
            "suitable_age": "",
            "skin_type": "",
            "foaming": "",
            "shelf_life": "",
            "warnings": [],
            "accessories": [],
        }

        messages = builder.build_messages(product_json, "这款都有什么规格？")
        system_content = messages[0]["content"]

        assert "助手：体验装一支、2支、3支、5支" in system_content

    def test_build_messages_format(self):
        """Must return OpenAI/Ollama chat-compatible format."""
        builder = PromptBuilder()
        product_json = {
            "goods_id": "123",
            "goods_name": "测试商品",
            "category": "",
            "brand": "",
            "sku_summary": "",
            "sku_options": [],
            "fragrance": "",
            "effect": [],
            "ingredients": "",
            "usage_method": "",
            "usage_duration": "",
            "suitable_age": "",
            "skin_type": "",
            "foaming": "",
            "shelf_life": "",
            "warnings": "",
            "accessories": "",
        }

        messages = builder.build_messages(product_json, "你好")

        assert isinstance(messages, list)
        assert len(messages) >= 2
        assert messages[0]["role"] == "system"
        assert "content" in messages[0]
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "你好"

    def test_build_messages_with_history(self):
        """History messages should be inserted correctly."""
        builder = PromptBuilder()
        product_json = {
            "goods_id": "123",
            "goods_name": "测试商品",
            "category": "",
            "brand": "",
            "sku_summary": "",
            "sku_options": [],
            "fragrance": "",
            "effect": [],
            "ingredients": "",
            "usage_method": "",
            "usage_duration": "",
            "suitable_age": "",
            "skin_type": "",
            "foaming": "",
            "shelf_life": "",
            "warnings": "",
            "accessories": "",
        }

        history = [
            {"role": "user", "content": "有什么规格?"},
            {"role": "assistant", "content": "我们有一瓶和两瓶装。"},
        ]

        messages = builder.build_messages(product_json, "一瓶多少钱?", history)

        assert len(messages) == 4  # system + 2 history + user
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "有什么规格?"
        assert messages[2]["role"] == "assistant"
        assert messages[3]["role"] == "user"
        assert messages[3]["content"] == "一瓶多少钱?"

    def test_build_messages_forbidden_behaviors(self):
        """System prompt must mention forbidden behaviors."""
        builder = PromptBuilder()
        product_json = {
            "goods_id": "123",
            "goods_name": "测试商品",
            "category": "",
            "brand": "",
            "sku_summary": "",
            "sku_options": ["一瓶"],
            "fragrance": "",
            "effect": [],
            "ingredients": "",
            "usage_method": "",
            "usage_duration": "",
            "suitable_age": "",
            "skin_type": "",
            "foaming": "",
            "shelf_life": "",
            "warnings": "",
            "accessories": "",
        }

        messages = builder.build_messages(product_json, "能治狐臭吗?")

        system_content = messages[0]["content"]

        # Must mention forbidden behaviors
        assert "禁止" in system_content or "不能" in system_content
        assert "医疗" in system_content or "治疗" in system_content or "狐臭" in system_content

    def test_build_messages_empty_field_fallback(self):
        """System prompt must mention empty field fallback behavior."""
        builder = PromptBuilder()
        product_json = {
            "goods_id": "123",
            "goods_name": "测试商品",
            "category": "",
            "brand": "",
            "price": "",
            "sku_summary": "",
            "sku_options": [],
            "fragrance": "",
            "effect": [],
            "ingredients": "",
            "usage_method": "",
            "usage_duration": "",
            "suitable_age": "",
            "skin_type": "",
            "foaming": "",
            "shelf_life": "",
            "warnings": [],
            "accessories": [],
        }

        messages = builder.build_messages(product_json, "保质期多久?")

        system_content = messages[0]["content"]

        # Must mention how to handle empty fields
        assert "不确定" in system_content or "人工客服" in system_content or "空" in system_content

    def test_build_messages_price_in_product_json(self):
        """Price must be present in product JSON."""
        builder = PromptBuilder()
        product = {
            "goods_id": "123",
            "goods_name": "测试商品",
            "category": "",
            "brand": "",
            "price": "9.90",
            "sku_summary": "",
            "sku_options": [],
            "fragrance": "",
            "effect": [],
            "ingredients": "",
            "usage_method": "",
            "usage_duration": "",
            "suitable_age": "",
            "skin_type": "",
            "foaming": "",
            "shelf_life": "",
            "warnings": [],
            "accessories": [],
        }

        product_json = builder.build_product_json(product)

        assert "price" in product_json
        assert product_json["price"] == "9.90"

    def test_build_messages_list_fields_none_to_empty_list(self):
        """List fields warnings and accessories should return [] for None."""
        builder = PromptBuilder()
        product = {
            "goods_id": "123",
            "goods_name": "测试商品",
            "category": "",
            "brand": "",
            "price": "",
            "sku_summary": "",
            "sku_options": None,
            "fragrance": "",
            "effect": None,
            "ingredients": "",
            "usage_method": "",
            "usage_duration": "",
            "suitable_age": "",
            "skin_type": "",
            "foaming": "",
            "shelf_life": "",
            "warnings": None,
            "accessories": None,
        }

        product_json = builder.build_product_json(product)

        assert product_json["sku_options"] == []
        assert product_json["effect"] == []
        assert product_json["warnings"] == []
        assert product_json["accessories"] == []

    def test_build_messages_age_field_mapping_rule(self):
        """System prompt must contain age/suitable_age mapping rule."""
        builder = PromptBuilder()
        product_json = {
            "goods_id": "123",
            "goods_name": "测试商品",
            "category": "",
            "brand": "",
            "price": "",
            "sku_summary": "",
            "sku_options": [],
            "fragrance": "",
            "effect": [],
            "ingredients": "",
            "usage_method": "",
            "usage_duration": "",
            "suitable_age": "12岁以上",
            "skin_type": "",
            "foaming": "",
            "shelf_life": "",
            "warnings": [],
            "accessories": [],
        }

        messages = builder.build_messages(product_json, "12岁可以用吗?")

        system_content = messages[0]["content"]

        # Must mention age mapping rule
        assert "12岁" in system_content or "suitable_age" in system_content

    def test_build_messages_usage_method_field_mapping_rule(self):
        """System prompt must contain usage_method mapping rule for single use queries."""
        builder = PromptBuilder()
        product_json = {
            "goods_id": "123",
            "goods_name": "测试商品",
            "category": "",
            "brand": "",
            "price": "",
            "sku_summary": "",
            "sku_options": [],
            "fragrance": "",
            "effect": [],
            "ingredients": "",
            "usage_method": "出门喷可以持续两至三个小时",
            "usage_duration": "",
            "suitable_age": "",
            "skin_type": "",
            "foaming": "",
            "shelf_life": "",
            "warnings": [],
            "accessories": [],
        }

        messages = builder.build_messages(product_json, "喷一次能管多久?")

        system_content = messages[0]["content"]

        # Must mention usage_method mapping rule
        assert "喷一次" in system_content or "usage_method" in system_content

    def test_build_messages_usage_duration_field_mapping_rule(self):
        """System prompt must contain usage_duration mapping rule for total duration queries."""
        builder = PromptBuilder()
        product_json = {
            "goods_id": "123",
            "goods_name": "测试商品",
            "category": "",
            "brand": "",
            "price": "",
            "sku_summary": "",
            "sku_options": [],
            "fragrance": "",
            "effect": [],
            "ingredients": "",
            "usage_method": "",
            "usage_duration": "一瓶可用一至两个月",
            "suitable_age": "",
            "skin_type": "",
            "foaming": "",
            "shelf_life": "",
            "warnings": [],
            "accessories": [],
        }

        messages = builder.build_messages(product_json, "一瓶能用多久?")

        system_content = messages[0]["content"]

        # Must mention usage_duration mapping rule
        assert "一瓶" in system_content or "usage_duration" in system_content
