"""
Unit tests for V3LightweightAgent

Tests the agent wrapper without calling Ollama. Uses FakeLLMClient for deterministic testing.
"""
import pytest
import sys
import importlib.util
from dataclasses import dataclass
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent

# Load v3_lightweight_agent module directly without triggering __init__.py
agent_path = project_root / "Agent" / "CustomerAgent" / "custom" / "v3_lightweight_agent.py"
spec_agent = importlib.util.spec_from_file_location("v3_lightweight_agent", agent_path)
agent_module = importlib.util.module_from_spec(spec_agent)
spec_agent.loader.exec_module(agent_module)

V3LightweightAgent = agent_module.V3LightweightAgent
V3ReplyResult = agent_module.V3ReplyResult

# Load prompt_builder module directly
builder_path = project_root / "Agent" / "CustomerAgent" / "custom" / "prompt_builder.py"
spec_builder = importlib.util.spec_from_file_location("prompt_builder", builder_path)
builder_module = importlib.util.module_from_spec(spec_builder)
spec_builder.loader.exec_module(builder_module)

PromptBuilder = builder_module.PromptBuilder

# Load response_validator module directly
validator_path = project_root / "Agent" / "CustomerAgent" / "custom" / "response_validator.py"
spec_validator = importlib.util.spec_from_file_location("response_validator", validator_path)
validator_module = importlib.util.module_from_spec(spec_validator)
spec_validator.loader.exec_module(validator_module)

handle_fallback = validator_module.handle_fallback


@dataclass
class FakeLocalLLMResponse:
    """Fake LLM response matching LocalLLMResponse interface."""
    success: bool
    content: str
    error: str | None = None


class FakeLLMClient:
    """Fake LLM client for testing."""

    def __init__(self, content: str, success: bool = True, error: str | None = None):
        self.content = content
        self.success = success
        self.error = error
        self.last_messages = None
        self.last_max_tokens = None
        self.last_temperature = None

    def chat_sync(self, messages: list[dict], max_tokens: int, temperature: float) -> FakeLocalLLMResponse:
        """Simulate chat_sync call."""
        self.last_messages = messages
        self.last_max_tokens = max_tokens
        self.last_temperature = temperature

        return FakeLocalLLMResponse(
            success=self.success,
            content=self.content,
            error=self.error
        )


# Test product data
TEST_PRODUCT = {
    "goods_id": "test123",
    "goods_name": "测试商品",
    "category": "护肤",
    "brand": "测试品牌",
    "price": "99.00",
    "sku_summary": "50ml",
    "sku_options": ["单瓶", "两瓶装"],
    "fragrance": "清香",
    "effect": ["保湿", "滋润"],
    "ingredients": "水、甘油",
    "usage_method": "每日早晚使用",
    "usage_duration": "一瓶可用一个月",
    "suitable_age": "成年人适用",
    "skin_type": "所有肤质",
    "foaming": "",
    "shelf_life": "",
    "warnings": None,
    "accessories": None,
}


def test_normal_reply_valid_true():
    """When LLM returns valid reply, raw_reply == final_reply."""
    fake_llm = FakeLLMClient(content="这个商品的价格是99.00元。", success=True)
    agent = V3LightweightAgent(llm_client=fake_llm)

    result = agent.generate_reply(TEST_PRODUCT, "这个多少钱?")

    assert result.valid is True
    assert result.raw_reply == "这个商品的价格是99.00元。"
    assert result.final_reply == result.raw_reply
    assert result.error is None
    assert result.latency_ms >= 0  # Can be 0 for very fast execution


def test_validation_failed_uses_fallback():
    """When validation fails, final_reply uses fallback."""
    # Reply makes up a price not in product - should trigger price validation failure
    # TEST_PRODUCT has price: "99.00"
    fake_llm = FakeLLMClient(content="这个商品只要50元，比其他家都便宜。", success=True)
    agent = V3LightweightAgent(llm_client=fake_llm)

    result = agent.generate_reply(TEST_PRODUCT, "这个多少钱?")

    assert result.valid is False
    assert result.fallback_type != ""
    # final_reply should be fallback, not raw_reply
    assert result.final_reply != result.raw_reply
    assert result.error is None


def test_llm_success_false_returns_fallback_and_error():
    """When LLM call fails, returns safe fallback and error."""
    fake_llm = FakeLLMClient(content="", success=False, error="Ollama connection timeout")
    agent = V3LightweightAgent(llm_client=fake_llm)

    result = agent.generate_reply(TEST_PRODUCT, "这个多少钱?")

    assert result.valid is False
    assert result.error == "Ollama connection timeout"
    assert result.fallback_type == "llm_failure"
    # Should use safe fallback
    assert "咨询" in result.final_reply or "客服" in result.final_reply
    assert result.raw_reply == ""


def test_history_passed_to_prompt_builder():
    """History is passed to PromptBuilder and appears in messages."""
    fake_llm = FakeLLMClient(content="好的。", success=True)
    agent = V3LightweightAgent(llm_client=fake_llm)

    history = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "您好"}]
    result = agent.generate_reply(TEST_PRODUCT, "谢谢", history=history)

    # Check that history was passed to LLM client
    assert fake_llm.last_messages is not None
    # Should have system message + history + user query
    messages = fake_llm.last_messages
    assert len(messages) >= 3  # system + history + user

    # Find the history in messages
    history_found = False
    for msg in messages:
        if msg.get("role") == "user" and msg.get("content") == "你好":
            history_found = True
            break
    assert history_found, "History not found in messages"


def test_temperature_and_max_tokens_passed_to_chat_sync():
    """Temperature and max_tokens are passed to chat_sync."""
    fake_llm = FakeLLMClient(content="测试回复", success=True)
    agent = V3LightweightAgent(
        llm_client=fake_llm,
        temperature=0.5,
        max_tokens=150
    )

    result = agent.generate_reply(TEST_PRODUCT, "测试问题")

    assert fake_llm.last_temperature == 0.5
    assert fake_llm.last_max_tokens == 150


def test_dependency_injection():
    """Agent supports dependency injection of PromptBuilder."""
    custom_builder = PromptBuilder()
    fake_llm = FakeLLMClient(content="测试", success=True)
    agent = V3LightweightAgent(
        llm_client=fake_llm,
        prompt_builder=custom_builder
    )

    assert agent.prompt_builder is custom_builder


def test_exception_during_pipeline():
    """Exception during pipeline returns safe fallback."""
    class BrokenLLMClient:
        def chat_sync(self, messages, max_tokens, temperature):
            raise RuntimeError("Unexpected error")

    agent = V3LightweightAgent(llm_client=BrokenLLMClient())
    result = agent.generate_reply(TEST_PRODUCT, "测试")

    assert result.valid is False
    assert result.error is not None
    assert "Unexpected error" in result.error
    assert result.fallback_type == "pipeline_error"
    # Should use safe fallback
    assert "咨询" in result.final_reply or "客服" in result.final_reply


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
