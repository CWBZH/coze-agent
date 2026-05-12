"""
商品检索词提取工具。

同步期和运行期共用这一套规则，避免一个地方会识别“湿敷棉”，另一个地方识别不出来。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Set


STOP_TERMS: Set[str] = {
    "你们", "我们", "这个", "那个", "什么", "怎么", "推荐", "一下", "一个", "一款",
    "有没有", "有吗", "有么", "有", "吗", "呢", "啊", "呀", "想要", "想买", "想看",
    "我要", "要", "适合", "哪个", "哪种", "那种", "一些", "其他", "或者", "还有",
    "帮我", "看看", "随便", "介绍", "好物", "请问", "能否", "给我", "可以", "比较",
    "非常", "特别", "更", "最", "多少", "几片", "几抽", "价格", "多少钱", "商品",
    "产品", "下单", "购买", "买", "卖", "店里", "店铺",
    "小孩子", "孩子", "能用", "可以用", "觉得", "味道", "不是", "不好", "好闻",
    "真的", "真人", "说话", "怎么办", "就是",
}

PRODUCT_PHRASES: Set[str] = {
    "湿敷棉", "敷脸棉", "化妆棉", "卸妆棉", "棉片", "水疗棉", "美容棉",
    "洗脸巾", "棉柔巾", "柔纸巾", "面巾", "卷筒洗脸巾",
    "香水", "香氛", "香氛喷雾", "喷雾", "女士香水", "花香调", "茉莉花香", "栀子花",
    "面膜", "湿巾", "纸巾",
}

ROUTE_PRODUCT_TERMS: Set[str] = PRODUCT_PHRASES | {
    "套装", "套盒", "组合装", "全套", "微风", "茉莉", "栀子",
}

ALIAS_GROUPS: Dict[str, List[str]] = {
    "湿敷棉": ["化妆棉", "敷脸棉", "棉片", "水疗棉"],
    "化妆棉": ["湿敷棉", "敷脸棉", "卸妆棉", "棉片"],
    "香氛": ["香水", "香氛喷雾", "喷雾"],
    "香水": ["香氛", "香氛喷雾", "女士香水"],
    "洗脸巾": ["棉柔巾", "面巾"],
    "棉柔巾": ["洗脸巾", "柔纸巾", "面巾"],
}

WEIGHTS: Dict[str, int] = {
    "core": 100,
    "alias": 72,
    "sku": 62,
    "attribute": 36,
    "category": 18,
}


def normalize_text(text: Any) -> str:
    text = str(text or "").lower()
    text = text.replace("ｍｌ", "ml").replace("毫升", "ml")
    text = re.sub(r"\s+", "", text)
    return text


def _add_term(terms: Dict[str, Dict[str, Any]], term: str, term_type: str, source: str = "") -> None:
    term = normalize_text(term).strip("：:，,。.!！?？[]【】()（）")
    if len(term) < 2 or term in STOP_TERMS:
        return
    if re.fullmatch(r"\d+", term):
        return

    weight = WEIGHTS.get(term_type, 10)
    existing = terms.get(term)
    if not existing or weight > existing["weight"]:
        terms[term] = {
            "term": term,
            "term_type": term_type,
            "weight": weight,
            "source": source[:100],
        }


def _parse_specs(specifications: Any) -> List[str]:
    if not specifications:
        return []

    specs = specifications
    if isinstance(specifications, str):
        try:
            specs = json.loads(specifications)
        except json.JSONDecodeError:
            specs = specifications

    items: List[str] = []
    if isinstance(specs, list):
        items = [str(item) for item in specs]
    elif isinstance(specs, dict):
        items = [f"{key}: {value}" for key, value in specs.items()]
    else:
        items = [x for x in re.split(r"[/、\n]", str(specs)) if x.strip()]
    return items


def extract_product_terms(
    goods_name: str,
    specifications: Any = None,
    extracted_content: str = "",
) -> List[Dict[str, Any]]:
    """从商品名、规格、详情中提取可检索词。"""
    terms: Dict[str, Dict[str, Any]] = {}
    name = normalize_text(goods_name)
    content_lines = [
        line for line in str(extracted_content or "").splitlines()
        if "商品分类" not in line
    ]
    content = normalize_text("\n".join(content_lines))
    all_specs = _parse_specs(specifications)
    non_category_specs = [
        item for item in all_specs
        if not item.strip().startswith("商品分类")
        and "商品分类:" not in item
        and "商品分类：" not in item
    ]
    spec_text = normalize_text(" ".join(non_category_specs))
    full_text = f"{name} {spec_text} {content}"

    for phrase in PRODUCT_PHRASES:
        normalized = normalize_text(phrase)
        if normalized in full_text:
            _add_term(terms, phrase, "core", "phrase")
            for alias in ALIAS_GROUPS.get(phrase, []):
                _add_term(terms, alias, "alias", f"alias:{phrase}")

    for item in all_specs:
        normalized = item.strip()
        if normalized.startswith("商品分类") or "商品分类:" in normalized or "商品分类：" in normalized:
            category = re.split(r"[:：]", normalized, maxsplit=1)[-1]
            for part in re.split(r"[>/／、\s]+", category):
                _add_term(terms, part, "category", "category")
            continue

        if normalized.startswith("款式") or normalized.startswith("规格"):
            normalized = re.split(r"[:：]", normalized, maxsplit=1)[-1]
        _add_term(terms, normalized, "sku", "sku")

        normalized_sku = normalize_text(normalized)
        if "全套" in normalized_sku or re.search(r"(?:2|3|二|两|三)\s*盒", normalized_sku):
            _add_term(terms, "套装", "sku", "sku_combo")

        for match in re.findall(r"\d+\s*(?:包|片|抽|卷|瓶|盒|ml|g|克)", normalized, flags=re.I):
            _add_term(terms, match, "sku", "sku_part")
        for part in re.split(r"[+＋*/，,、\s]+", normalized):
            _add_term(terms, part, "attribute", "sku_part")

    for match in re.findall(r"\d+\s*(?:包|片|抽|卷|瓶|盒|ml|g|克)", full_text, flags=re.I):
        _add_term(terms, match, "sku", "quantity")

    try:
        import jieba
        tokens = jieba.lcut(goods_name)
    except Exception:
        tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", goods_name)

    for token in tokens:
        _add_term(terms, token, "attribute", "jieba")

    return sorted(terms.values(), key=lambda item: item["weight"], reverse=True)


def extract_query_terms(query: str, known_terms: Iterable[str] | None = None) -> List[str]:
    """从买家口语中提取商品检索词，优先保留同步期词典里的长词。"""
    q = normalize_text(query)
    q = q.replace("内容：", "").replace("内容:", "")
    terms: List[str] = []

    candidates = set(PRODUCT_PHRASES)
    if known_terms:
        candidates.update(str(term) for term in known_terms)

    for term in sorted(candidates, key=lambda x: len(normalize_text(x)), reverse=True):
        normalized = normalize_text(term)
        if len(normalized) >= 2 and normalized in q and normalized not in terms:
            terms.append(normalized)

    try:
        import jieba
        tokens = jieba.lcut(q)
    except Exception:
        tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", q)

    for token in tokens:
        token = normalize_text(token)
        if len(token) < 2 or token in STOP_TERMS or token in terms:
            continue
        if re.fullmatch(r"\d+", token):
            continue
        terms.append(token)

    return terms


def extract_route_product_terms(query: str) -> List[str]:
    """仅提取可用于路由到商品推荐/商品咨询的强商品词。"""
    q = normalize_text(query)
    q = q.replace("内容：", "").replace("内容:", "")
    terms: List[str] = []
    for term in sorted(ROUTE_PRODUCT_TERMS, key=lambda x: len(normalize_text(x)), reverse=True):
        normalized = normalize_text(term)
        if len(normalized) >= 2 and normalized in q and normalized not in terms:
            terms.append(normalized)
    return terms
