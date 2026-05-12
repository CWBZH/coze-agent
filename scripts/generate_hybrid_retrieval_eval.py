from __future__ import annotations

import csv
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import config
from core.di_container import configure_standard_services

OUT_DIR = ROOT / "docs" / "eval"
DATASET_PATH = OUT_DIR / "hybrid_retrieval_eval_dataset_1000.csv"
RESULT_PATH = OUT_DIR / "hybrid_retrieval_eval_results_1000.csv"
REPORT_PATH = OUT_DIR / "hybrid_retrieval_eval_review.md"


def _case(
    query: str,
    expected_intent: str,
    expected_sub_intent: str,
    expected_policy: str,
    expected_scope: str,
    locked: bool,
    category: str,
) -> Dict[str, Any]:
    return {
        "query": query,
        "expected_intent": expected_intent,
        "expected_sub_intent": expected_sub_intent,
        "expected_policy": expected_policy,
        "expected_scope": expected_scope,
        "locked": locked,
        "category": category,
    }


def build_dataset(size: int = 1000) -> List[Dict[str, Any]]:
    locked_goods_id = True
    no_goods = False

    templates: List[Dict[str, Any]] = []

    usage_duration = [
        "能使用多久", "使用时长有吗", "一瓶能用多久", "一支用多久", "一盒可以用几天",
        "这个可以用几天", "这款能用几次", "用多长时间", "几天用完", "一瓶用多久",
    ]
    usage_method = [
        "怎么用", "什么时候用", "一天几次", "早上用还是晚上用", "喷哪里",
        "涂哪里", "如何使用", "用法是什么", "白天能用吗", "敷多久",
    ]
    foaming = [
        "起泡多吗", "泡沫多吗", "气泡多吗", "这支洗面奶气泡多吗", "泡泡丰富吗",
        "泡沫绵密吗", "洗面奶起泡怎么样", "这个泡多不多", "容易起泡吗", "泡沫细腻吗",
    ]
    ingredient = [
        "成分是什么", "含不含酒精", "有没有酒精", "有香精吗", "材质是什么",
        "里面有什么成分", "这个成分安全吗", "含酒精吗", "有没有香精", "主要成分有哪些",
    ]
    age = [
        "12岁能用吗", "小孩可以用吗", "儿童能用吗", "宝宝能用吗", "孕妇可以用吗",
        "敏感肌能用吗", "学生能用吗", "老人能用吗", "青少年可以用吗", "婴儿能用吗",
    ]
    sku = [
        "几片", "多少片", "几抽", "多少抽", "多大规格", "容量多少",
        "多少ml", "几瓶", "几包", "规格是什么",
    ]
    price = [
        "多少钱", "价格多少", "几块钱", "几元", "贵吗", "便宜吗",
        "有优惠吗", "现在什么价", "这款价格", "多少钱一瓶",
    ]
    recommend = [
        "推荐一款洗面奶", "有没有香水", "想买洗脸巾", "哪款湿敷棉好",
        "推荐一个便宜点的", "有什么香氛", "想看喷雾", "哪种最香",
        "换一款", "有没有类似的",
    ]
    logistics = [
        "几天到", "多久到", "什么时候发货", "几天发货", "发什么快递",
        "物流到哪了", "催发货", "什么时候送到", "快递多久", "到货要几天",
    ]
    after_sales = [
        "我要退款", "可以退货吗", "发错了", "少发了", "坏了",
        "漏液了", "破损了", "没收到", "申请售后", "买错了",
    ]
    general = [
        "在吗", "你好", "有人吗", "？", "嗯", "好的", "ok", "说话", "有人回复吗", "谢谢",
    ]

    for q in usage_duration:
        templates.append(_case(q, "pre_sale", "usage_duration", "current_product", "current_product", locked_goods_id, "usage_duration_locked"))
        templates.append(_case(q, "pre_sale", "usage_duration", "clarify_product", "unknown", no_goods, "usage_duration_no_goods"))
    for q in usage_method:
        templates.append(_case(q, "pre_sale", "usage_method", "current_product", "current_product", locked_goods_id, "usage_method_locked"))
        templates.append(_case(q, "pre_sale", "usage_method", "clarify_product", "unknown", no_goods, "usage_method_no_goods"))
    for q in foaming:
        templates.append(_case(q, "pre_sale", "foaming", "current_product", "current_product", locked_goods_id, "foaming_locked"))
        templates.append(_case(q, "pre_sale", "foaming", "clarify_product", "unknown", no_goods, "foaming_no_goods"))
    for q in ingredient:
        templates.append(_case(q, "pre_sale", "ingredient", "current_product", "current_product", locked_goods_id, "ingredient_locked"))
        templates.append(_case(q, "pre_sale", "ingredient", "clarify_product", "unknown", no_goods, "ingredient_no_goods"))
    for q in age:
        templates.append(_case(q, "pre_sale", "age_safety", "current_product", "current_product", locked_goods_id, "age_locked"))
        templates.append(_case(q, "pre_sale", "age_safety", "clarify_product", "unknown", no_goods, "age_no_goods"))
    for q in sku:
        templates.append(_case(q, "pre_sale", "sku_spec", "current_product", "current_product", locked_goods_id, "sku_locked"))
        templates.append(_case(q, "pre_sale", "sku_spec", "clarify_product", "unknown", no_goods, "sku_no_goods"))
    for q in price:
        templates.append(_case(q, "pre_sale", "price", "current_product", "current_product", locked_goods_id, "price_locked"))
        templates.append(_case(q, "pre_sale", "price", "clarify_product", "unknown", no_goods, "price_no_goods"))
    for q in recommend:
        expected_sub = "fragrance" if "最香" in q else "product_discovery"
        templates.append(_case(q, "recommend", expected_sub, "product_candidates", "product_candidates", locked_goods_id, "recommend"))
        templates.append(_case(q, "recommend", expected_sub, "product_candidates", "product_candidates", no_goods, "recommend"))
    for q in logistics:
        templates.append(_case(q, "logistics", "logistics_delivery", "shop_knowledge", "shop", locked_goods_id, "logistics"))
        templates.append(_case(q, "logistics", "logistics_delivery", "shop_knowledge", "shop", no_goods, "logistics"))
    for q in after_sales:
        templates.append(_case(q, "after_sales", "none", "shop_knowledge", "shop", locked_goods_id, "after_sales"))
        templates.append(_case(q, "after_sales", "none", "shop_knowledge", "shop", no_goods, "after_sales"))
    for q in general:
        templates.append(_case(q, "general", "none", "shop_knowledge", "none", locked_goods_id, "general"))
        templates.append(_case(q, "general", "none", "shop_knowledge", "none", no_goods, "general"))

    random.seed(20260511)
    rows = []
    for idx in range(size):
        base = dict(templates[idx % len(templates)])
        base["case_id"] = idx + 1
        rows.append(base)
    random.shuffle(rows)
    for idx, row in enumerate(rows, 1):
        row["case_id"] = idx
    return rows


def evaluate(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    configure_standard_services(config)
    from Agent.CustomerAgent.custom.customer_agent import CustomerAgent

    agent = CustomerAgent()
    results = []
    for row in rows:
        locked_goods_id = "934239100155" if row["locked"] else None
        state = {
            "session_id": f"eval_hybrid_{row['case_id']}",
            "user_query": row["query"],
            "messages": [],
            "current_intent": "unknown",
            "locked_goods_id": locked_goods_id,
            "shop_id": 323473738,
        }
        routed = agent.node_router(state)
        routed = agent._ensure_retrieval_policy(routed)
        actual = {
            "actual_intent": routed.get("current_intent", ""),
            "actual_sub_intent": routed.get("sub_intent", "none"),
            "actual_policy": routed.get("retrieval_policy", "none"),
            "actual_scope": routed.get("entity_scope", "unknown"),
            "confidence": routed.get("sub_intent_confidence", 0),
            "matched_terms": "|".join(routed.get("sub_intent_terms") or []),
        }
        checks = {
            "intent_ok": actual["actual_intent"] == row["expected_intent"],
            "sub_intent_ok": actual["actual_sub_intent"] == row["expected_sub_intent"],
            "policy_ok": actual["actual_policy"] == row["expected_policy"],
            "scope_ok": actual["actual_scope"] == row["expected_scope"],
        }
        results.append({**row, **actual, **checks, "all_ok": all(checks.values())})
    return results


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_report(results: List[Dict[str, Any]]) -> str:
    total = len(results)
    metrics = {
        "intent": sum(1 for r in results if r["intent_ok"]),
        "sub_intent": sum(1 for r in results if r["sub_intent_ok"]),
        "retrieval_policy": sum(1 for r in results if r["policy_ok"]),
        "entity_scope": sum(1 for r in results if r["scope_ok"]),
        "all": sum(1 for r in results if r["all_ok"]),
    }
    by_category = defaultdict(lambda: Counter(total=0, all_ok=0, policy_ok=0, sub_intent_ok=0))
    for row in results:
        bucket = by_category[row["category"]]
        bucket["total"] += 1
        bucket["all_ok"] += int(row["all_ok"])
        bucket["policy_ok"] += int(row["policy_ok"])
        bucket["sub_intent_ok"] += int(row["sub_intent_ok"])

    attr_wrong_candidate = [
        r for r in results
        if r["expected_policy"] in {"current_product", "clarify_product"}
        and r["actual_policy"] == "product_candidates"
    ]
    failures = [r for r in results if not r["all_ok"]][:30]

    lines = [
        "# 混合检索二级路由 1000 条回归 Review",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 测试集: `{DATASET_PATH.name}`",
        f"- 结果集: `{RESULT_PATH.name}`",
        f"- 样本数: {total}",
        "",
        "## 总体指标",
        "",
        "| 指标 | 正确数 | 准确率 |",
        "| --- | ---: | ---: |",
    ]
    for name, count in metrics.items():
        lines.append(f"| {name} | {count}/{total} | {count / total:.2%} |")

    lines.extend([
        "",
        "## 关键护栏",
        "",
        f"- 属性问题误进入商品候选召回: {len(attr_wrong_candidate)}",
        "- 目标: 0",
        "",
        "## 分类明细",
        "",
        "| 分类 | 样本数 | 全链路准确率 | 策略准确率 | 二级意图准确率 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for category in sorted(by_category):
        bucket = by_category[category]
        lines.append(
            f"| {category} | {bucket['total']} | "
            f"{bucket['all_ok'] / bucket['total']:.2%} | "
            f"{bucket['policy_ok'] / bucket['total']:.2%} | "
            f"{bucket['sub_intent_ok'] / bucket['total']:.2%} |"
        )

    lines.extend(["", "## 失败样例 Top 30", ""])
    if failures:
        lines.extend([
            "| case_id | query | expected | actual |",
            "| ---: | --- | --- | --- |",
        ])
        for r in failures:
            expected = f"{r['expected_intent']} / {r['expected_sub_intent']} / {r['expected_policy']} / {r['expected_scope']}"
            actual = f"{r['actual_intent']} / {r['actual_sub_intent']} / {r['actual_policy']} / {r['actual_scope']}"
            lines.append(f"| {r['case_id']} | {r['query']} | {expected} | {actual} |")
    else:
        lines.append("无失败样例。")

    lines.extend([
        "",
        "## Review 结论",
        "",
        "本轮评测重点验证二级意图和 retrieval_policy 的边界：属性问答必须进入当前商品或澄清链路，推荐找货才允许进入商品候选召回。",
        "后续如果扩展商品属性字段和 Qdrant 商品级向量片段，应继续使用本评测集作为回归门禁。",
    ])
    return "\n".join(lines)


def main() -> None:
    rows = build_dataset(1000)
    write_csv(DATASET_PATH, rows)
    results = evaluate(rows)
    write_csv(RESULT_PATH, results)
    REPORT_PATH.write_text(build_report(results), encoding="utf-8")
    print(f"dataset={DATASET_PATH}")
    print(f"results={RESULT_PATH}")
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
