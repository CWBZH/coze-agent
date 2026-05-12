"""
LLM 客户端模块

封装与 LLM API 的交互，提供类型安全的请求和响应处理。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from dataclasses import dataclass

try:
    from openai import AsyncOpenAI
except ImportError:
    raise ImportError("openai package is required: pip install openai>=1.109.1")

from utils.logger_loguru import get_logger
from utils.volcengine_models import ChatCompletionsRequest

logger = get_logger("LLMClient")


@dataclass
class LLMResponse:
    """LLM 响应封装"""
    content: Optional[str]
    tool_calls: Optional[List[Any]]
    raw_response: Any

    @property
    def has_tool_calls(self) -> bool:
        """是否有工具调用"""
        return self.tool_calls is not None and len(self.tool_calls) > 0


class LLMClient:
    """LLM 客户端封装"""

    def __init__(
        self,
        api_key: str,
        api_base: str,
        model_name: str,
        temperature: float,
        tools: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        初始化 LLM 客户端

        Args:
            api_key: API 密钥
            api_base: API 基础地址
            model_name: 模型名称
            temperature: 温度参数
            tools: 可用工具列表
        """
        self.api_key = api_key
        self.api_base = api_base
        self.model_name = model_name
        self.temperature = temperature
        self.tools = tools or []

        self._client: Optional[AsyncOpenAI] = None

    async def initialize(self) -> None:
        """初始化 OpenAI 客户端"""
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.api_base or None,
            timeout=60.0,
        )
        logger.debug(f"LLM 客户端初始化成功: model={self.model_name}")

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tool_choice: str = "auto",
    ) -> LLMResponse:
        """
        发送聊天请求到 LLM

        Args:
            messages: 消息列表
            tool_choice: 工具选择策略

        Returns:
            LLMResponse 封装的响应
        """
        if not self._client:
            raise RuntimeError("LLM 客户端未初始化，请先调用 initialize()")

        # 1. 构建请求参数字典
        request_dict: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
        }

        if self.tools:
            request_dict["tools"] = self.tools
            request_dict["tool_choice"] = tool_choice

        # 2. 使用 Pydantic 模型验证请求参数
        try:
            validated_request = ChatCompletionsRequest(**request_dict)
            logger.debug("请求参数验证通过")
        except Exception as e:
            logger.error(f"请求参数验证失败: {e}")
            raise

        # 3. 调试日志：输出发送给 LLM 的消息（限制内容长度，避免泄露敏感信息）
        logger.debug(f"发送给 LLM 的消息数: {len(messages)}")
        for i, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            # 只记录消息角色和长度，不记录内容（避免泄露用户隐私）
            content = str(msg.get("content", ""))
            logger.debug(f"消息 {i} [{role}]: 长度={len(content)}")

        # 4. 构造 payload 并强制剔除 Ollama 不兼容参数
        payload = validated_request.model_dump(exclude_none=True)

        # 强制删除 Ollama 本地模型不支持的参数（belt-and-suspenders）
        OLLAMA_UNSUPPORTED_KEYS = [
            "reasoning_effort",
            "thinking",
            "max_completion_tokens",
            "service_tier",
            "stream_options",
            "logprobs",
            "top_logprobs",
            "parallel_tool_calls",
            "tools",        # Ollama 本地模型不支持 function calling
            "tool_choice",  # 依赖 tools，一并删除
        ]
        for key in OLLAMA_UNSUPPORTED_KEYS:
            if key in payload:
                del payload[key]
                logger.debug(f"已从 payload 中剔除不兼容参数: {key}")

        # 5. 调用 API
        response = await self._client.chat.completions.create(**payload)

        # 6. 兼容处理：支持 OpenAI 和 Ollama 两种返回格式
        # Ollama 可能返回字符串或非标准格式
        if isinstance(response, str):
            # Ollama 直接返回字符串
            logger.debug(f"Ollama 直接返回字符串: {response[:200]}...")
            return LLMResponse(
                content=response,
                tool_calls=None,
                raw_response=response,
            )

        # 标准 OpenAI 格式
        if hasattr(response, 'choices') and response.choices:
            message = response.choices[0].message
        else:
            # Ollama 返回的 dict 格式
            if isinstance(response, dict):
                content = response.get('message', {}).get('content', '')
                logger.debug(f"Ollama dict 格式返回: {content[:200]}...")
                return LLMResponse(
                    content=content,
                    tool_calls=None,
                    raw_response=response,
                )
            else:
                # 未知格式，尝试转为字符串
                logger.warning(f"未知响应格式: {type(response)}")
                return LLMResponse(
                    content=str(response),
                    tool_calls=None,
                    raw_response=response,
                )

        # 7. 记录 token 使用情况（仅 OpenAI 格式）
        if hasattr(response, 'usage') and response.usage:
            logger.debug(f"使用了 {response.usage.total_tokens} tokens "
                        f"(prompt: {response.usage.prompt_tokens}, "
                        f"completion: {response.usage.completion_tokens})")

        # 8. 调试日志：输出 LLM 的响应
        if hasattr(message, 'tool_calls') and message.tool_calls:
            tool_names = [tc.function.name for tc in message.tool_calls]
            logger.info(f"LLM 决定调用工具: {tool_names}")
        else:
            logger.debug(f"LLM 直接回复: {str(message.content)[:200]}...")

        return LLMResponse(
            content=message.content if hasattr(message, 'content') else str(message),
            tool_calls=message.tool_calls if hasattr(message, 'tool_calls') else None,
            raw_response=response,
        )
