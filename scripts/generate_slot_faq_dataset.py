from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from database.knowledge_service import KnowledgeService


OUTPUT_DIR = Path("docs/eval")
CSV_PATH = OUTPUT_DIR / "product_slot_faq_1000.csv"
JSONL_PATH = OUTPUT_DIR / "product_slot_faq_1000.jsonl"
SUMMARY_PATH = OUTPUT_DIR / "product_slot_faq_1000_summary.md"


@dataclass(frozen=True)
class SlotSpec:
    slot_id: str
    field: str
    count: int
    answer_policy: str
    templates: List[str]


SLOT_SPECS: List[SlotSpec] = [
    SlotSpec(
        "sku_options",
        "attributes.sku_options",
        150,
        "读取 sku_options；若为空读取 sku_summary；不要把容量和可选 SKU 混成同一类。",
        ["有什么规格", "这款有几种规格", "有几瓶装", "可以买几瓶", "这个有哪些款式", "有套装吗", "规格都有哪些", "买几瓶合适"],
    ),
    SlotSpec(
        "effect",
        "attributes.effect",
        130,
        "读取 effect；问到具体功效时只基于 effect 判断，字段无该功效则说明当前标注的功效。",
        ["这个有什么效果", "能{effect_term}吗", "可以{effect_term}吗", "主要作用是什么", "这个好用在哪", "功效是什么", "有没有{effect_term}效果"],
    ),
    SlotSpec(
        "price",
        "price",
        100,
        "读取 price；多规格价格提示以下单页为准。",
        ["多少钱", "这个价格多少", "怎么卖", "贵不贵", "几块钱", "有优惠吗", "一瓶多少钱", "多瓶多少钱"],
    ),
    SlotSpec(
        "skin_type",
        "attributes.skin_type",
        95,
        "读取 skin_type；不要映射到 suitable_age。",
        ["黄皮能用吗", "敏感肌可以用吗", "油皮适合吗", "干皮能用吗", "适合什么肤质", "黑皮可以用吗", "学生党肤质能用吗", "混油皮能用不"],
    ),
    SlotSpec(
        "usage_method",
        "attributes.usage_method",
        90,
        "读取 usage_method；如果用户问部位但字段没有部位，应提示未明确标注部位。",
        ["怎么用", "这个怎么使用", "喷哪里", "涂哪里", "一天用几次", "早上用还是晚上用", "出门前怎么用", "使用方法是什么"],
    ),
    SlotSpec(
        "ingredients",
        "attributes.ingredients",
        80,
        "读取 ingredients；涉及过敏源时只提示成分信息，不做医学承诺。",
        ["有什么成分", "含酒精吗", "有香精吗", "成分安全吗", "主要成分是什么", "材质是什么", "敏感肌看成分可以吗", "里面有什么"],
    ),
    SlotSpec(
        "usage_duration",
        "attributes.usage_duration",
        75,
        "读取 usage_duration；按用量不同补充说明。",
        ["能用多久", "一瓶可以用多久", "一支能用几天", "大概能用几个月", "耐用吗", "用多长时间", "一瓶够用吗"],
    ),
    SlotSpec(
        "suitable_age",
        "attributes.suitable_age",
        70,
        "读取 suitable_age；只处理年龄/儿童类问题。",
        ["几岁可以用", "12岁能用吗", "小孩可以用吗", "儿童能用吗", "宝宝能用吗", "青少年可以用吗", "多大年龄适合"],
    ),
    SlotSpec(
        "fragrance",
        "attributes.fragrance",
        60,
        "读取 fragrance；不要编造不存在的香型。",
        ["什么味道", "香味是什么", "味道重吗", "好闻吗", "留香久吗", "有没有清香味", "是什么香型"],
    ),
    SlotSpec(
        "brand",
        "attributes.brand",
        50,
        "读取 brand；字段为空则说明页面未明确标注。",
        ["什么品牌", "什么牌子", "哪个牌子的", "这是什么牌子", "品牌名是什么", "是哪个品牌", "牌子叫什么"],
    ),
    SlotSpec(
        "category",
        "attributes.category",
        40,
        "读取 category；用于确认商品类型。",
        ["这是什么类型", "这是洗面奶吗", "这是香水吗", "属于什么类目", "这个是干嘛的", "是什么产品"],
    ),
    SlotSpec(
        "warnings",
        "attributes.warnings",
        40,
        "读取 warnings；孕妇/禁忌/注意事项不可用 suitable_age 代答。",
        ["孕妇能用吗", "哺乳期可以用吗", "有什么禁忌", "有什么注意事项", "会刺激吗", "过敏能用吗", "敏感人群要注意什么"],
    ),
    SlotSpec(
        "shelf_life",
        "attributes.shelf_life",
        35,
        "读取 shelf_life；字段为空必须兜底。",
        ["保质期多久", "能放多久", "什么时候过期", "生产日期怎么看", "保质期几年", "开封后能放多久"],
    ),
    SlotSpec(
        "foaming",
        "attributes.foaming",
        25,
        "读取 foaming；适用于洁面类起泡问题。",
        ["泡沫多吗", "起泡吗", "泡泡丰富吗", "容易起泡吗", "是低泡的吗", "洗面奶泡沫怎么样"],
    ),
    SlotSpec(
        "accessories",
        "attributes.accessories",
        25,
        "读取 accessories；不要把赠品当主 SKU。",
        ["有赠品吗", "送什么", "有小样吗", "会送洗脸巾吗", "配件有什么", "有没有附带东西"],
    ),
    SlotSpec(
        "unknown_product_slot",
        "",
        30,
        "商品追问但字段不明确，应追问或转 LLM 兜底。",
        ["这个怎么样", "这个好不好", "适合我吗", "买这个行吗", "这个靠谱吗", "这个可以吗"],
    ),
    SlotSpec(
        "non_product",
        "",
        50,
        "非商品属性问题，不应走 Product Slot。",
        ["什么时候发货", "可以退货吗", "我要人工", "在吗", "怎么付款", "快递多久到", "能退吗", "谢谢", "有人吗", "我要投诉"],
    ),
]


EFFECT_TERMS = ["止汗", "除臭", "保湿", "美白", "清洁", "控油", "留香", "提亮", "卸妆", "补水", "防晒"]


def load_products() -> List[Dict[str, Any]]:
    service = KnowledgeService()
    products = []
    for product in service.list_products_by_shop(1):
        try:
            attrs = json.loads(product.attribute_json or "{}")
        except Exception:
            attrs = {}
        products.append(
            {
                "goods_id": str(product.goods_id),
                "goods_name": product.goods_name or "",
                "price": product.price or "",
                "attributes": attrs,
            }
        )
    if not products:
        raise RuntimeError("No products found for shop_id=1")
    return products


def field_value(product: Dict[str, Any], field: str) -> Any:
    if not field:
        return ""
    if field == "price":
        return product.get("price", "")
    if field.startswith("attributes."):
        key = field.split(".", 1)[1]
        return (product.get("attributes") or {}).get(key, "")
    return ""


def normalize_value(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(item) for item in value if str(item).strip())
    return str(value or "").strip()


def iter_cases(products: List[Dict[str, Any]], seed: int = 42) -> Iterable[Dict[str, Any]]:
    rng = random.Random(seed)
    case_no = 1
    for spec in SLOT_SPECS:
        for _ in range(spec.count):
            product = rng.choice(products)
            template = rng.choice(spec.templates)
            effect_term = rng.choice(EFFECT_TERMS)
            query = template.format(effect_term=effect_term)
            value = field_value(product, spec.field)
            value_text = normalize_value(value)
            yield {
                "case_id": f"slot-{case_no:04d}",
                "goods_id": product["goods_id"],
                "goods_name": product["goods_name"],
                "query": query,
                "expected_intent": "pre_sale" if spec.slot_id not in {"non_product"} else "non_product",
                "expected_slot": spec.slot_id,
                "expected_fact_field": spec.field,
                "field_value": value_text,
                "answer_policy": spec.answer_policy,
                "is_empty_field": "true" if not value_text else "false",
                "source": "generated_from_current_shop_products_v1",
            }
            case_no += 1


def write_outputs(rows: List[Dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case_id",
        "goods_id",
        "goods_name",
        "query",
        "expected_intent",
        "expected_slot",
        "expected_fact_field",
        "field_value",
        "answer_policy",
        "is_empty_field",
        "source",
    ]
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with JSONL_PATH.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    slot_counts: Dict[str, int] = {}
    empty_counts: Dict[str, int] = {}
    for row in rows:
        slot = row["expected_slot"]
        slot_counts[slot] = slot_counts.get(slot, 0) + 1
        if row["is_empty_field"] == "true":
            empty_counts[slot] = empty_counts.get(slot, 0) + 1

    lines = [
        "# Product Slot FAQ Dataset Summary",
        "",
        f"- total_cases: {len(rows)}",
        f"- csv: `{CSV_PATH.as_posix()}`",
        f"- jsonl: `{JSONL_PATH.as_posix()}`",
        "",
        "## Slot Distribution",
        "",
        "| slot | cases | empty_field_cases |",
        "| --- | ---: | ---: |",
    ]
    for slot, count in sorted(slot_counts.items()):
        lines.append(f"| `{slot}` | {count} | {empty_counts.get(slot, 0)} |")
    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    products = load_products()
    rows = list(iter_cases(products))
    if len(rows) != 1000:
        raise RuntimeError(f"Expected 1000 rows, got {len(rows)}")
    write_outputs(rows)
    print(f"generated {len(rows)} rows")
    print(CSV_PATH)
    print(JSONL_PATH)
    print(SUMMARY_PATH)


if __name__ == "__main__":
    main()
