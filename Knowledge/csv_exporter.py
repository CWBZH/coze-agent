"""Export product knowledge as an editable FastGPT CSV."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime


MANUAL_FIELD_KEYS = [
    "category",
    "sku_options",
    "sku_summary",
    "effect",
    "usage_method",
    "usage_duration",
    "suitable_age",
    "skin_type",
    "fragrance",
    "ingredients",
    "shelf_life",
    "warnings",
    "manual_notes",
]


def export_fastgpt_csv(db_manager, shop_db_id: int, output_path: str = None) -> str:
    from database.models import ProductKnowledge, Shop

    if output_path is None:
        output_path = f"./temp/fastgpt_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    with db_manager.session_scope() as session:
        shop = session.query(Shop).filter(Shop.id == shop_db_id).first()
        products = (
            session.query(ProductKnowledge)
            .filter(ProductKnowledge.shop_id == shop_db_id)
            .order_by(ProductKnowledge.id.asc())
            .all()
        )

        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=_fieldnames())
            writer.writeheader()
            for product in products:
                manual_attrs = _manual_attrs(product)
                content = _render_content(product, manual_attrs)
                metadata = {
                    "shop_db_id": shop_db_id,
                    "shop_platform_id": getattr(shop, "shop_id", ""),
                    "shop_name": getattr(shop, "shop_name", ""),
                    "goods_id": str(product.goods_id or ""),
                    "goods_name": product.goods_name or "",
                    "source": "product_knowledge_ui",
                    "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                row = {
                    "doc_id": f"{getattr(shop, 'shop_id', shop_db_id)}:{product.goods_id}",
                    "shop_platform_id": getattr(shop, "shop_id", ""),
                    "shop_db_id": shop_db_id,
                    "shop_name": getattr(shop, "shop_name", ""),
                    "goods_id": product.goods_id,
                    "goods_name": product.goods_name,
                    "price": product.price or "",
                    "sold_quantity": product.sold_quantity or "",
                    "specifications": product.specifications or "",
                    "fastgpt_question": _default_question(product, manual_attrs),
                    "fastgpt_answer": content,
                    "content": content,
                    "metadata_json": json.dumps(metadata, ensure_ascii=False),
                }
                for key in MANUAL_FIELD_KEYS:
                    row[key] = _cell(manual_attrs.get(key))
                writer.writerow(row)

        for product in products:
            if product.knowledge_status == "pending":
                product.knowledge_status = "synced"

    return output_path


def _fieldnames() -> list[str]:
    return [
        "doc_id",
        "shop_platform_id",
        "shop_db_id",
        "shop_name",
        "goods_id",
        "goods_name",
        "price",
        "sold_quantity",
        "specifications",
        *MANUAL_FIELD_KEYS,
        "fastgpt_question",
        "fastgpt_answer",
        "content",
        "metadata_json",
    ]


def _manual_attrs(product) -> dict:
    raw = _json_dict(product.raw_detail_json)
    attrs = raw.get("manual_attributes") or {}
    return attrs if isinstance(attrs, dict) else {}


def _json_dict(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(str(raw))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if str(item).strip())
    return str(value)


def _default_question(product, attrs: dict) -> str:
    category = attrs.get("category") or ""
    return f"{product.goods_name} 的规格、用法、适用人群和注意事项是什么？" if not category else f"{category} {product.goods_name} 怎么选？"


def _render_content(product, attrs: dict) -> str:
    lines = [
        f"商品名称: {product.goods_name or ''}",
        f"商品ID: {product.goods_id or ''}",
        f"价格: {product.price or ''}",
    ]

    labels = {
        "category": "主类目",
        "sku_options": "可选规格",
        "sku_summary": "默认推荐规格",
        "effect": "功效卖点",
        "usage_method": "使用方法",
        "usage_duration": "使用时长",
        "suitable_age": "适用年龄",
        "skin_type": "适用肤质/人群",
        "fragrance": "香味",
        "ingredients": "成分/材质",
        "shelf_life": "保质期",
        "warnings": "注意事项",
        "manual_notes": "人工补充话术",
    }
    for key in MANUAL_FIELD_KEYS:
        value = _cell(attrs.get(key))
        if value:
            lines.append(f"{labels[key]}: {value}")

    if product.specifications:
        lines.append(f"平台规格: {product.specifications}")
    return "\n".join(lines)
