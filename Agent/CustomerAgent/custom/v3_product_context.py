"""V3 Product Context Adapter - Normalizes MySQL ProductKnowledge records to 18-field dict."""
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProductContextResult:
    """Result of product context adaptation."""
    product: dict
    warnings: list[str] = field(default_factory=list)


class ProductContextAdapter:
    """Adapts MySQL ProductKnowledge records to standardized 18-field product dict."""

    # All 18 required fields (no image)
    REQUIRED_FIELDS = [
        "goods_id", "goods_name", "category", "brand", "price", "sku_summary",
        "sku_options", "fragrance", "effect", "ingredients", "usage_method",
        "usage_duration", "suitable_age", "skin_type", "foaming", "shelf_life",
        "warnings", "accessories"
    ]

    # Fields that must be lists
    LIST_FIELDS = ["sku_options", "effect", "warnings", "accessories"]

    # Top-level fields from record
    TOP_LEVEL_FIELDS = ["goods_id", "goods_name", "price", "price_range", "specifications", "attribute_json"]

    # Known attribute fields that can be merged
    KNOWN_ATTR_FIELDS = [
        "goods_id", "goods_name", "category", "brand", "price", "sku_summary",
        "sku_options", "fragrance", "effect", "ingredients", "usage_method",
        "usage_duration", "suitable_age", "skin_type", "foaming", "shelf_life",
        "warnings", "accessories"
    ]

    @classmethod
    def from_record(cls, record: Any) -> ProductContextResult:
        """
        Adapt a MySQL ProductKnowledge record to standardized product dict.

        Args:
            record: Dict or object with attributes

        Returns:
            ProductContextResult with product dict and warnings
        """
        warnings = []

        # Extract fields from dict or object
        data = cls._extract_record_data(record)

        # Initialize product dict with defaults
        product = {f: "" for f in cls.REQUIRED_FIELDS}
        for f in cls.LIST_FIELDS:
            product[f] = []

        # Fill top-level fields first
        top_level = {}
        if "goods_id" in data:
            top_level["goods_id"] = data["goods_id"]
        if "goods_name" in data:
            top_level["goods_name"] = data["goods_name"]

        # Price logic: use price if non-empty, otherwise price_range
        if "price" in data and data["price"]:
            top_level["price"] = data["price"]
        elif "price_range" in data and data["price_range"]:
            top_level["price"] = data["price_range"]

        # Store specifications for fallback
        specifications = data.get("specifications", "")

        # Parse attribute_json
        attr_data = {}
        attribute_json = data.get("attribute_json")

        if attribute_json:
            if isinstance(attribute_json, dict):
                attr_data = attribute_json
            elif isinstance(attribute_json, str):
                if attribute_json.strip():
                    try:
                        parsed = json.loads(attribute_json)
                        if isinstance(parsed, dict):
                            attr_data = parsed
                    except json.JSONDecodeError:
                        warnings.append("invalid_attribute_json")

        # Merge: top-level first, then attributes
        # Top-level goods_id/goods_name/price are protected from empty attr values
        for k, v in top_level.items():
            product[k] = v

        # Merge known attribute fields
        unknown_fields = []
        for k, v in attr_data.items():
            if k in cls.KNOWN_ATTR_FIELDS:
                # Attribute cannot erase non-empty top-level goods_id/goods_name/price
                if k in ["goods_id", "goods_name", "price"]:
                    if k in product and product[k]:
                        # Top-level is non-empty, skip attr if empty
                        if v == "" or v is None:
                            continue

                # Fill value
                if v is not None:
                    product[k] = v
            else:
                # Unknown field
                if v is not None and v != "":
                    unknown_fields.append(k)

        # Report unknown fields
        if unknown_fields:
            unknown_fields_sorted = sorted(unknown_fields)
            warnings.append(f"unknown_attribute_fields:{','.join(unknown_fields_sorted)}")

        # Normalize list fields
        for f in cls.LIST_FIELDS:
            product[f] = cls._normalize_list(product.get(f))

        # sku_summary fallback: use specifications if sku_summary empty
        if not product.get("sku_summary") and specifications:
            product["sku_summary"] = specifications

        # Ensure all string fields are strings
        for f in cls.REQUIRED_FIELDS:
            if f not in cls.LIST_FIELDS:
                if product.get(f) is None:
                    product[f] = ""
                elif not isinstance(product[f], str):
                    product[f] = str(product[f])

        return ProductContextResult(product=product, warnings=warnings)

    @classmethod
    def _extract_record_data(cls, record: Any) -> dict:
        """Extract fields from dict or object."""
        if isinstance(record, dict):
            return record

        # Object with attributes
        data = {}
        for f in cls.TOP_LEVEL_FIELDS:
            if hasattr(record, f):
                data[f] = getattr(record, f)
        return data

    @classmethod
    def _normalize_list(cls, value: Any) -> list:
        """Normalize value to list with proper string conversion."""
        if value is None or value == "":
            return []

        if isinstance(value, str):
            return [value]

        if isinstance(value, list):
            # Preserve order, stringify non-None items, skip None
            result = []
            for item in value:
                if item is not None:
                    result.append(str(item))
            return result

        # Fallback: convert to string and wrap in list
        return [str(value)]
