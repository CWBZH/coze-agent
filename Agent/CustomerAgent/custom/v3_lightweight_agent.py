"""
V3 Lightweight Customer Agent Service Shell
Provides a reusable agent wrapper for PromptBuilder + ResponseValidator pipeline.
"""
from dataclasses import dataclass
from typing import Optional
import time
import importlib.util
from pathlib import Path

# Load dependencies dynamically to avoid import issues
_current_dir = Path(__file__).parent
_prompt_builder_path = _current_dir / "prompt_builder.py"
_response_validator_path = _current_dir / "response_validator.py"

# Load PromptBuilder
_spec_builder = importlib.util.spec_from_file_location("prompt_builder", _prompt_builder_path)
_builder_module = importlib.util.module_from_spec(_spec_builder)
_spec_builder.loader.exec_module(_builder_module)
PromptBuilder = _builder_module.PromptBuilder

# Load response_validator
_spec_validator = importlib.util.spec_from_file_location("response_validator", _response_validator_path)
_validator_module = importlib.util.module_from_spec(_spec_validator)
_spec_validator.loader.exec_module(_validator_module)
validate_response = _validator_module.validate_response
handle_fallback = _validator_module.handle_fallback


def _normalize_llm_result(llm_result) -> tuple[bool, str, str | None]:
    """
    Normalize LLM result to (success, content, error) tuple.

    Supports:
    - LocalLLMResponse objects with .success, .content, .error attributes
    - Dict with 'success', 'reply', 'error' keys (backward compatibility)
    - Dict with 'success', 'content', 'error' keys
    - Tuple (reply, latency_ms) legacy format

    Returns:
        Tuple of (success: bool, content: str, error: str | None)
    """
    if hasattr(llm_result, 'success'):
        # LocalLLMResponse object
        return (llm_result.success, llm_result.content, llm_result.error)
    elif isinstance(llm_result, dict):
        # Dict format
        success = llm_result.get('success', False)
        # Support both 'reply' and 'content' keys
        content = llm_result.get('content') or llm_result.get('reply', '')
        error = llm_result.get('error')
        return (success, content, error)
    elif isinstance(llm_result, tuple):
        # Legacy tuple format: (reply, latency_ms)
        content = llm_result[0] if llm_result[0] else ""
        success = content != ""
        return (success, content, None)
    else:
        raise ValueError(f"Unexpected llm_result type: {type(llm_result)}")


@dataclass
class V3ReplyResult:
    """Result from V3 lightweight agent reply generation."""
    raw_reply: str
    final_reply: str
    valid: bool
    reason: str
    fallback_type: str
    latency_ms: float
    error: Optional[str]


class V3LightweightAgent:
    """
    Lightweight V3 customer agent that combines PromptBuilder + ResponseValidator.
    Does not depend on MySQL/Redis/Qdrant. Suitable for offline testing and experimentation.
    """

    def __init__(
        self,
        llm_client=None,
        prompt_builder=None,
        temperature: float = 0.0,
        max_tokens: int = 90
    ):
        """
        Initialize V3 lightweight agent with dependency injection.

        Args:
            llm_client: LLM client with chat_sync(messages, max_tokens, temperature) method
            prompt_builder: PromptBuilder instance (default: new PromptBuilder())
            temperature: Temperature for LLM calls
            max_tokens: Max tokens for LLM calls
        """
        self.llm_client = llm_client
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate_reply(
        self,
        product: dict,
        user_query: str,
        history: Optional[list] = None
    ) -> V3ReplyResult:
        """
        Generate a validated reply for a product query.

        Args:
            product: Product dict with 18 fields (as per PromptBuilder spec)
            user_query: User's question
            history: Optional conversation history list

        Returns:
            V3ReplyResult with raw_reply, final_reply, validation status, latency, etc.
        """
        start_time = time.time()
        raw_reply = ""
        final_reply = ""
        valid = False
        reason = ""
        fallback_type = ""
        error = None

        try:
            # Step 1: Build product JSON
            product_json = self.prompt_builder.build_product_json(product)

            # Step 2: Build messages
            messages = self.prompt_builder.build_messages(product_json, user_query, history)

            # Step 3: Call LLM
            if self.llm_client is None:
                raise ValueError("llm_client is not configured")

            llm_result = self.llm_client.chat_sync(
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )

            # Normalize LLM result to (success, content, error)
            success, raw_reply, error = _normalize_llm_result(llm_result)

            if not success:
                # LLM call failed - use safe fallback
                final_reply = handle_fallback("llm_failure", product_json, user_query)
                fallback_type = "llm_failure"
                error = error or "LLM call failed"
                latency_ms = (time.time() - start_time) * 1000
                return V3ReplyResult(
                    raw_reply=raw_reply,
                    final_reply=final_reply,
                    valid=False,
                    reason="LLM call failed",
                    fallback_type=fallback_type,
                    latency_ms=latency_ms,
                    error=error
                )

            # Step 4: Validate response
            validation_result = validate_response(raw_reply, product_json, user_query)

            if validation_result.valid:
                # Valid reply - use as-is
                final_reply = raw_reply
                valid = True
                reason = validation_result.reason
                fallback_type = ""
            else:
                # Invalid reply - apply fallback
                final_reply = handle_fallback(
                    validation_result.fallback_type,
                    product_json,
                    user_query
                )
                valid = False
                reason = validation_result.reason
                fallback_type = validation_result.fallback_type

        except Exception as e:
            # Exception during pipeline - use safe fallback
            final_reply = handle_fallback("pipeline_error", product_json if 'product_json' in locals() else None, user_query)
            fallback_type = "pipeline_error"
            error = str(e)
            raw_reply = raw_reply or ""

        latency_ms = (time.time() - start_time) * 1000

        return V3ReplyResult(
            raw_reply=raw_reply,
            final_reply=final_reply,
            valid=valid,
            reason=reason,
            fallback_type=fallback_type,
            latency_ms=latency_ms,
            error=error
        )