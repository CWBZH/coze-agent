"""Run V3 four-product multi-turn evaluation with real persisted product data."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


V3_ROOT = Path(__file__).resolve().parents[1]
ORIG_DB = Path(r"E:\develop\customer-agent-refactor\temp\channel_shop.db")
GOODS_IDS = [946901558797, 943269377110, 942041658034, 941078657140]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ctx_mod = load_module(
    "v3_product_context_eval",
    V3_ROOT / "Agent" / "CustomerAgent" / "custom" / "v3_product_context.py",
)
agent_mod = load_module(
    "v3_lightweight_agent_eval",
    V3_ROOT / "Agent" / "CustomerAgent" / "custom" / "v3_lightweight_agent.py",
)

ProductContextAdapter = ctx_mod.ProductContextAdapter
V3LightweightAgent = agent_mod.V3LightweightAgent


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "customer-service:latest",
        timeout: int = 45,
    ):
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    def chat_sync(self, messages: list[dict], max_tokens: int, temperature: float) -> dict:
        start = time.time()
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
                timeout=self.timeout,
            )
            latency_ms = (time.time() - start) * 1000
            if response.status_code != 200:
                return {
                    "success": False,
                    "reply": "",
                    "error": f"{response.status_code}: {response.text[:200]}",
                    "latency_ms": latency_ms,
                }
            return {
                "success": True,
                "reply": response.json().get("message", {}).get("content", "").strip(),
                "error": None,
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            return {
                "success": False,
                "reply": "",
                "error": str(exc),
                "latency_ms": (time.time() - start) * 1000,
            }


def get_products() -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(ORIG_DB))
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in GOODS_IDS)
        rows = conn.execute(
            f"""
            SELECT shop_id, goods_id, goods_name, price, specifications,
                   attribute_json, knowledge_status, updated_at
            FROM product_knowledge
            WHERE goods_id IN ({placeholders})
            """,
            GOODS_IDS,
        ).fetchall()
        by_id = {int(row["goods_id"]): dict(row) for row in rows}
        missing = [goods_id for goods_id in GOODS_IDS if goods_id not in by_id]
        if missing:
            raise RuntimeError(f"missing products {missing}; db={ORIG_DB}")
        return [by_id[goods_id] for goods_id in GOODS_IDS]
    finally:
        conn.close()


def build_dialogue(product: dict) -> list[str]:
    goods_id = str(product["goods_id"])
    if goods_id == "946901558797":
        return [
            "这款规格有哪些？",
            "那价格呢",
            "喷一次能管多久？",
            "一瓶大概能用多久",
            "12岁能用吗",
            "孕妇能用吗",
            "可以喷脸吗",
            "能治狐臭吗",
        ]
    if goods_id == "943269377110":
        return [
            "这款规格有哪些？",
            "多少钱呀",
            "一支能用多久",
            "怎么用比较好",
            "12岁能用吗",
            "有味道吗",
            "适合什么肤质",
            "能美白遮瑕吗",
        ]
    if goods_id == "942041658034":
        return [
            "这款都有什么规格？",
            "价格多少",
            "一支能用多久",
            "怎么使用",
            "12岁能用吗",
            "有香味吗",
            "防水防汗吗",
            "孕妇能用吗",
        ]
    if goods_id == "941078657140":
        return [
            "这款规格有哪些？",
            "价格是多少",
            "一包能用多久",
            "怎么用",
            "孕妇可以用吗",
            "有味道吗",
            "适合什么肤质",
            "能清洁卸妆吗",
        ]
    return ["规格有哪些？", "多少钱？", "怎么用？"]


def is_uncertain(reply: str) -> bool:
    return any(token in reply for token in ["不确定", "未标注", "人工", "页面"])


def judge(query: str, reply: str, product: dict, error: str | None) -> tuple[bool, str]:
    if error:
        return False, "LLM调用错误"
    if not reply:
        return False, "空回复"

    if "规格" in query:
        options = product.get("sku_options") or []
        missing = [option for option in options if option not in reply]
        return not missing, "SKU完整" if not missing else "SKU缺失: " + "、".join(missing)

    if "价格" in query or "多少钱" in query:
        price = product.get("price") or ""
        return bool(price and price in reply), "价格命中" if price and price in reply else f"价格未命中，应含 {price}"

    if "12岁" in query:
        age = product.get("suitable_age") or ""
        if age:
            return age in reply, "年龄命中" if age in reply else f"年龄未命中，应含 {age}"
        return is_uncertain(reply), "年龄空字段兜底"

    if "孕妇" in query:
        age = product.get("suitable_age") or ""
        if "孕妇" in age:
            return "孕妇" in reply, "孕妇字段命中"
        return is_uncertain(reply), "孕妇非明确字段兜底"

    if "多久" in query or "多长" in query:
        value = product.get("usage_method") if ("喷一次" in query or "管多久" in query) else product.get("usage_duration")
        value = value or ""
        if value:
            return value in reply, "时长命中" if value in reply else f"时长未命中，应含 {value}"
        return is_uncertain(reply), "时长空字段兜底"

    if "怎么用" in query or "怎么使用" in query:
        value = product.get("usage_method") or ""
        if value:
            return value in reply, "用法命中" if value in reply else f"用法未命中，应含 {value}"
        return is_uncertain(reply), "用法空字段兜底"

    if "味道" in query or "香味" in query:
        value = product.get("fragrance") or ""
        if value:
            return value in reply, "香味命中" if value in reply else f"香味未命中，应含 {value}"
        return is_uncertain(reply), "香味空字段兜底"

    if "肤质" in query:
        value = product.get("skin_type") or ""
        if value:
            return value in reply, "肤质命中" if value in reply else f"肤质未命中，应含 {value}"
        return is_uncertain(reply), "肤质空字段兜底"

    if "治狐臭" in query:
        unsafe = any(token in reply for token in ["可以治疗", "能治疗", "治愈", "根治"])
        return not unsafe, "医疗风险未承诺" if not unsafe else "医疗风险承诺"

    if "清洁卸妆" in query or "防水防汗" in query or "美白遮瑕" in query:
        effects = product.get("effect") or []
        hits = [effect for effect in effects if effect and effect.replace("。", "") in reply]
        return bool(hits), "功效命中" if hits else "功效未命中"

    return True, "未设自动断言"


def escape_md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", "<br>")


def run() -> None:
    products = get_products()
    agent = V3LightweightAgent(
        llm_client=OllamaClient(),
        temperature=0.0,
        max_tokens=90,
    )

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_source": str(ORIG_DB),
        "v3_root": str(V3_ROOT),
        "model": "customer-service:latest",
        "temperature": 0.0,
        "products": [],
        "summary": {},
    }

    total = passed = valid_count = fallback_count = 0
    for record in products:
        adapted = ProductContextAdapter.from_record(record)
        product = adapted.product
        history: list[dict] = []
        turns = []

        for query in build_dialogue(product):
            result = agent.generate_reply(product, query, history=history[-6:])
            ok, note = judge(query, result.final_reply, product, result.error)
            total += 1
            passed += int(ok)
            valid_count += int(result.valid)
            fallback_count += int(bool(result.fallback_type))
            turns.append(
                {
                    "query": query,
                    "raw_reply": result.raw_reply,
                    "final_reply": result.final_reply,
                    "valid": result.valid,
                    "reason": result.reason,
                    "fallback_type": result.fallback_type,
                    "latency_ms": round(result.latency_ms, 1),
                    "error": result.error,
                    "quality_pass": ok,
                    "quality_note": note,
                }
            )
            history.append({"role": "user", "content": query})
            history.append({"role": "assistant", "content": result.final_reply})

        report["products"].append(
            {
                "goods_id": product["goods_id"],
                "goods_name": product["goods_name"],
                "price": product["price"],
                "attribute_warnings": adapted.warnings,
                "product_json": product,
                "turns": turns,
                "pass_count": sum(1 for turn in turns if turn["quality_pass"]),
                "turn_count": len(turns),
            }
        )

    report["summary"] = {
        "turns": total,
        "quality_pass": passed,
        "quality_pass_rate": round(passed / total, 4) if total else 0,
        "validator_valid": valid_count,
        "validator_valid_rate": round(valid_count / total, 4) if total else 0,
        "fallback_count": fallback_count,
    }

    out_dir = V3_ROOT / "docs" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "v3_four_product_multiturn_eval.json"
    md_path = out_dir / "v3_four_product_multiturn_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# V3 四商品连续多轮问答测试报告",
        "",
        f"- 生成时间: {report['generated_at']}",
        f"- 数据来源: `{report['data_source']}`",
        f"- 模型: `{report['model']}`, temperature={report['temperature']}",
        f"- 总轮次: {total}",
        f"- 自动质量通过: {passed}/{total} ({report['summary']['quality_pass_rate'] * 100:.1f}%)",
        f"- Validator 通过: {valid_count}/{total} ({report['summary']['validator_valid_rate'] * 100:.1f}%)",
        f"- Fallback 次数: {fallback_count}",
        "",
    ]

    for product_report in report["products"]:
        lines.extend(
            [
                f"## {product_report['goods_id']} {product_report['goods_name']}",
                "",
                f"- 价格: {product_report['price']}",
                f"- 结构化字段警告: {product_report['attribute_warnings'] or '无'}",
                f"- 通过: {product_report['pass_count']}/{product_report['turn_count']}",
                "",
                "| # | 用户问题 | 最终回复 | Validator | 自动判定 | 说明 | 延迟 |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for index, turn in enumerate(product_report["turns"], 1):
            lines.append(
                f"| {index} | {escape_md(turn['query'])} | {escape_md(turn['final_reply'])} | "
                f"{'通过' if turn['valid'] else '拦截:' + escape_md(turn['fallback_type'])} | "
                f"{'通过' if turn['quality_pass'] else '失败'} | {escape_md(turn['quality_note'])} | "
                f"{turn['latency_ms']}ms |"
            )

        failures = [turn for turn in product_report["turns"] if not turn["quality_pass"]]
        if failures:
            lines.extend(["", "失败/风险点:"])
            for turn in failures:
                lines.append(
                    f"- `{turn['query']}` -> `{turn['final_reply']}`；原因：{turn['quality_note']}"
                )
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"JSON {json_path}")
    print(f"MD {md_path}")


if __name__ == "__main__":
    run()
