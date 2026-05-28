from __future__ import annotations

from typing import Any


LIST_KEYS = (
    "goods",
    "onSaleGoods",
    "goodsList",
    "goods_list",
    "list",
    "records",
    "items",
    "data",
)


def parse_product_list(response_data: dict[str, Any] | None) -> dict[str, Any]:
    data = _result_data(response_data)
    goods_list = _find_goods_list(data)
    products = []
    for goods in goods_list:
        if not isinstance(goods, dict):
            continue
        min_price = _first_value(
            goods,
            "minOnSaleGroupPrice",
            "minPrice",
            "groupPrice",
            "price",
            "priceMin",
            "min_price",
        )
        max_price = _first_value(goods, "maxOnSaleGroupPrice", "maxPrice", "priceMax", "max_price", "price")
        product = {
            "goods_id": str(_first_value(goods, "goodsId", "goodsID", "goods_id", "id") or ""),
            "goods_name": str(_first_value(goods, "goodsName", "goods_name", "name", "title") or ""),
            "thumb_url": str(_first_value(goods, "thumbUrl", "thumb_url", "hdThumbUrl", "imageUrl", "image_url") or ""),
            "price": _format_price_range(min_price, max_price),
            "price_min": _price_to_cent(min_price),
            "price_max": _price_to_cent(max_price),
            "sold_quantity": _first_value(goods, "soldQuantity", "sold_quantity", "sales", "salesVolume", "soldQuantity30d") or 0,
            "sold_quantity_30d": _first_value(goods, "soldQuantity30d", "sold_quantity_30d") or 0,
            "quantity": _first_value(goods, "quantity", "stockCount", "stock", "inventory") or 0,
            "goods_type": _first_value(goods, "goodsType", "goods_type", "type") or "",
            "is_spike": bool(_first_value(goods, "isSpike", "is_spike") or False),
            "support_customize": bool(_first_value(goods, "supportCustomize", "support_customize") or False),
            "goods_url": str(_first_value(goods, "goodsUrl", "goods_url", "url") or ""),
            "tag": _tag_text(goods),
            "raw_item": goods,
        }
        if product["goods_id"]:
            products.append(product)
    return {"products": products, "total": _total_count(data, len(products))}


def parse_product_detail(response_data: dict[str, Any] | None) -> dict[str, Any]:
    data = _result_data(response_data)
    specifications = _specifications(data)
    categories = _first_value(data, "cats", "catList", "categoryList", "categories")
    if isinstance(categories, list):
        valid_categories = [str(item) for item in categories if item]
        if valid_categories:
            specifications.append(f"Category: {' > '.join(valid_categories)}")
    commit_info = _first_value(data, "goodsCommitInfo", "commitInfo")
    commit_info = commit_info if isinstance(commit_info, dict) else {}
    return {
        "goods_id": str(_first_value(data, "goods_id", "goodsId", "goodsID", "id") or ""),
        "goods_name": str(_first_value(data, "goods_name", "goodsName", "name", "title") or ""),
        "specifications": specifications[:50],
        "usage": str(_first_value(data, "usage", "usageMethod", "usage_method", "howToUse") or ""),
        "ingredients": str(_first_value(data, "ingredients", "ingredient", "composition") or ""),
        "shelf_life": str(_first_value(data, "shelf_life", "shelfLife", "expiry", "expiration") or commit_info.get("shelfLife") or ""),
        "warnings": str(_first_value(data, "warnings", "warning", "notice", "cautions") or ""),
        "manual_notes": str(_first_value(data, "manual_notes", "notes") or ""),
    }


def _result_data(response_data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(response_data, dict):
        return {}
    for key in ("result", "data"):
        value = response_data.get(key)
        if isinstance(value, dict):
            return value
    return response_data


def _find_goods_list(data: dict[str, Any]) -> list[Any]:
    for key in LIST_KEYS:
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _find_goods_list(value)
            if nested:
                return nested
    for value in data.values():
        if isinstance(value, dict):
            nested = _find_goods_list(value)
            if nested:
                return nested
    return []


def _first_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _total_count(data: dict[str, Any], default: int) -> int:
    value = _first_value(data, "total", "totalCount", "total_count", "count")
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _tag_text(goods: dict[str, Any]) -> str:
    tag = goods.get("goodsTag") or goods.get("goods_tag") or {}
    tags = tag.get("marketingTags") if isinstance(tag, dict) else None
    if isinstance(tags, list):
        return ", ".join(str(item) for item in tags if item)
    raw = _first_value(goods, "tag", "tags", "label")
    if isinstance(raw, list):
        return ", ".join(str(item) for item in raw if item)
    return str(raw or "")


def _specifications(data: dict[str, Any]) -> list[str]:
    skus = _first_value(data, "skus", "skuList", "sku_list") or []
    if not isinstance(skus, list):
        return []
    specs = []
    for sku in skus:
        if not isinstance(sku, dict):
            continue
        spec_items = _first_value(sku, "spec", "specs", "properties") or []
        if not isinstance(spec_items, list):
            continue
        labels = []
        for item in spec_items:
            if not isinstance(item, dict):
                continue
            parent = _first_value(item, "parent_name", "parentName", "parentSpecName", "parent_spec_name")
            name = _first_value(item, "spec_name", "specName", "value", "name")
            if parent and name:
                labels.append(f"{parent}: {name}")
            elif name:
                labels.append(str(name))
        if labels:
            specs.append(" | ".join(labels))
    return specs


def _format_price_range(min_price: Any, max_price: Any) -> str | None:
    if min_price not in (None, "") and max_price not in (None, "") and str(min_price) != str(max_price):
        return f"{_format_price(min_price)}-{_format_price(max_price)}"
    if min_price not in (None, ""):
        return _format_price(min_price)
    return None


def _price_to_cent(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        text = str(value)
        if "." in text:
            return int(round(float(text) * 100))
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_price(value: Any) -> str:
    cents = _price_to_cent(value)
    if cents is None:
        return str(value)
    return f"{cents / 100:.2f}"
