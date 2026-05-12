"""
V3.0 Prompt-only Experiment Script

Standalone experiment for testing V3.0 prompt-only pipeline without database dependencies.
Uses hardcoded product data and calls local Ollama customer-service:latest model.
"""
import time
import requests
import json
import sys
import importlib.util
from pathlib import Path
from typing import Any

# Load prompt_builder module directly without triggering __init__.py
# This avoids dependency on services that aren't initialized in standalone script
project_root = Path(__file__).parent.parent
module_path = project_root / "Agent" / "CustomerAgent" / "custom" / "prompt_builder.py"
spec = importlib.util.spec_from_file_location("prompt_builder", module_path)
prompt_builder_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prompt_builder_module)

PromptBuilder = prompt_builder_module.PromptBuilder


# Test product data (goods_id: 946901558797)
TEST_PRODUCT = {
    "goods_id": "946901558797",
    "goods_name": "净爽止汗喷雾保湿除臭净味爽身清新舒爽温和腋下止汗香体20ml",
    "category": "个护",
    "brand": "伊思棠",
    "price": "4.80-12.00",
    "sku_summary": "20ml",
    "sku_options": ["一瓶", "2瓶", "3瓶"],
    "fragrance": "清香",
    "effect": ["保湿", "止汗", "清香"],
    "ingredients": "酒精、香精",
    "usage_method": "出门喷可以持续两至三个小时",
    "usage_duration": "一瓶可用一至两个月",
    "suitable_age": "12岁以上能使用",
    "skin_type": "所有肤质均可",
    "foaming": "",
    "shelf_life": "",
    "warnings": None,
    "accessories": None,
}


# Test queries (at least 8)
TEST_QUERIES = [
    "规格有哪些?",
    "一瓶能用多久?",
    "喷一次能管多长时间?",
    "12岁可以用吗?",
    "孕妇能用吗?",
    "能治狐臭吗?",
    "可以喷脸吗?",
    "保质期多久?",
]


class OllamaClient:
    """Simple Ollama API client for experiment."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "customer-service:latest",
        temperature: float = 0.0,
        max_tokens: int = 90,
        timeout: int = 30
    ):
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def chat(self, messages: list[dict]) -> tuple[str, float]:
        """
        Send chat request to Ollama.

        Returns:
            Tuple of (response_text, latency_ms)
        """
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            }
        }

        start_time = time.time()
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout
            )
            latency_ms = (time.time() - start_time) * 1000

            if response.status_code != 200:
                raise Exception(f"Ollama API error: {response.status_code} - {response.text}")

            result = response.json()
            content = result.get("message", {}).get("content", "")
            return content.strip(), latency_ms

        except requests.exceptions.Timeout:
            latency_ms = (time.time() - start_time) * 1000
            raise Exception(f"Ollama request timeout after {self.timeout}s")
        except requests.exceptions.ConnectionError:
            raise Exception(f"Cannot connect to Ollama at {self.base_url}. Is Ollama running?")


def run_experiment():
    """Run V3.0 prompt-only experiment."""
    print("=" * 80)
    print("V3.0 Prompt-only Experiment - Slice 1")
    print("=" * 80)
    print()

    # Initialize components
    builder = PromptBuilder()
    ollama = OllamaClient()

    # Build product JSON
    print("Product JSON:")
    print("-" * 80)
    product_json = builder.build_product_json(TEST_PRODUCT)
    for field, value in product_json.items():
        print(f"  {field}: {value}")
    print()

    # Run test queries
    print("Test Queries:")
    print("-" * 80)

    results = []
    for i, query in enumerate(TEST_QUERIES, 1):
        print(f"\n[{i}/{len(TEST_QUERIES)}] Query: {query}")

        try:
            # Build messages
            messages = builder.build_messages(product_json, query)

            # Call Ollama
            reply, latency_ms = ollama.chat(messages)

            # Record result
            results.append({
                "query": query,
                "reply": reply,
                "latency_ms": latency_ms,
                "success": True
            })

            print(f"  Reply: {reply}")
            print(f"  Latency: {latency_ms:.1f}ms")

        except Exception as e:
            results.append({
                "query": query,
                "reply": f"ERROR: {str(e)}",
                "latency_ms": 0,
                "success": False
            })
            print(f"  ERROR: {str(e)}")

    # Print summary
    print()
    print("=" * 80)
    print("Summary")
    print("=" * 80)

    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    print(f"Total queries: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")

    if successful:
        avg_latency = sum(r["latency_ms"] for r in successful) / len(successful)
        max_latency = max(r["latency_ms"] for r in successful)
        min_latency = min(r["latency_ms"] for r in successful)
        print(f"\nLatency statistics:")
        print(f"  Average: {avg_latency:.1f}ms")
        print(f"  Min: {min_latency:.1f}ms")
        print(f"  Max: {max_latency:.1f}ms")

    # Print detailed results table
    print()
    print("Detailed Results:")
    print("-" * 80)
    print(f"{'Query':<30} {'Latency':<10} {'Reply'}")
    print("-" * 80)
    for r in results:
        reply_preview = r["reply"][:50] + "..." if len(r["reply"]) > 50 else r["reply"]
        print(f"{r['query']:<30} {r['latency_ms']:<10.1f} {reply_preview}")

    print()
    print("=" * 80)
    print("Experiment Complete")
    print("=" * 80)

    return results


if __name__ == "__main__":
    try:
        run_experiment()
    except KeyboardInterrupt:
        print("\nExperiment interrupted by user")
    except Exception as e:
        print(f"\nExperiment failed with error: {e}")
        import traceback
        traceback.print_exc()
