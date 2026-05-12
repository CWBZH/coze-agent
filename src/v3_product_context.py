"""V3 Product Context Adapter.

Converts MySQL ProductKnowledge-like records into 18-field product dicts
for PromptBuilder consumption.
"""

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProductContextResult:
    """Normalized product context with 18 fields for PromptBuilder."""

    goods_id: str | None = None
    goods_name: str = ""
    category: str = ""
    brand: str = ""
    price: str = ""
    sku_summary: str = ""
    sku_options: list[str] = field(default_factory=list)
    fragrance: str = ""
    effect: list[str] = field(default_factory=list)
    ingredients: str = ""
    usage_method: str = ""
    usage_duration: str = ""
    suitable_age: str = ""
    skin_type: str = ""
    foaming: str = ""
    shelf_life: str = ""
    warnings: list[str] = field(default_factory=list)
    accessories: list[str] = field(default_factory=list)


class ProductContextAdapter:
    """Adapts raw product data to ProductContextResult.

    Handles:
    - attribute_json parsing (dict, JSON string, empty/None, invalid JSON)
    - Field normalization (string fields → "", list fields → [])
    - Merge priority (top-level goods_id/goods_name/price override empty attr values)
    """

    def adapt(self, product_data: dict[str, Any]) -> ProductContextResult:
        """Convert product_data dict to ProductContextResult.

        Args:
            product_data: Raw product dict with top-level fields and attribute_json

        Returns:
            ProductContextResult with normalized 18 fields
        """
        attr = self._parse_attribute_json(product_data.get("attribute_json"))

        return ProductContextResult(
            goods_id=self._merge_field(product_data, attr, "goods_id", None),
            goods_name=self._merge_field(product_data, attr, "goods_name", ""),
            category=self._normalize_string(attr.get("category")),
            brand=self._normalize_string(attr.get("brand")),
            price=self._merge_field(product_data, attr, "price", ""),
            sku_summary=self._normalize_string(attr.get("sku_summary")),
            sku_options=self._normalize_list(attr.get("sku_options")),
            fragrance=self._normalize_string(attr.get("fragrance")),
            effect=self._normalize_list(attr.get("effect")),
            ingredients=self._normalize_string(attr.get("ingredients")),
            usage_method=self._normalize_string(attr.get("usage_method")),
            usage_duration=self._normalize_string(attr.get("usage_duration")),
            suitable_age=self._normalize_string(attr.get("suitable_age")),
            skin_type=self._normalize_string(attr.get("skin_type")),
            foaming=self._normalize_string(attr.get("foaming")),
            shelf_life=self._normalize_string(attr.get("shelf_life")),
            warnings=self._normalize_list(attr.get("warnings")),
            accessories=self._normalize_list(attr.get("accessories")),
        )

    def _parse_attribute_json(self, attr_json: Any) -> dict[str, Any]:
        """Parse attribute_json field.

        Handles:
        - dict: return as-is
        - JSON string: parse and validate
        - None/empty/invalid: return empty dict
        """
        if isinstance(attr_json, dict):
            return attr_json

        if isinstance(attr_json, str) and attr_json.strip():
            try:
                parsed = json.loads(attr_json)
                return parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, TypeError):
                return {}

        return {}

    def _merge_field(
        self,
        product_data: dict[str, Any],
        attr: dict[str, Any],
        field_name: str,
        default: str | None,
    ) -> str | None:
        """Merge top-level field with attr field.

        Priority:
        1. Top-level field if non-empty
        2. Attr field if non-empty
        3. Default value
        """
        top_level = product_data.get(field_name)
        attr_value = attr.get(field_name)

        if isinstance(top_level, str) and top_level.strip():
            return top_level

        if isinstance(attr_value, str) and attr_value.strip():
            return attr_value

        return default

    def _normalize_string(self, value: Any) -> str:
        """Normalize string field to empty string default."""
        if isinstance(value, str):
            return value
        return ""

    def _normalize_list(self, value: Any) -> list[str]:
        """Normalize list field to empty list default.

        Accepts:
        - list: return as-is (assume elements are strings)
        - Other types: return empty list
        """
        if isinstance(value, list):
            return value
        return []
