"""
本地 LLM 客户端

通过 Ollama 提供本地模型 API。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import httpx
import json

from utils.logger_loguru import get_logger

logger = get_logger("LocalLLMClient")


@dataclass
class LocalLLMConfig:
    """本地 LLM 配置"""
    enabled: bool = True
    base_url: str = "http://localhost:11434"
    model_name: str = "qwen2.5:7b"
    max_tokens: int = 50
    temperature: float = 0.7
    timeout: float = 60.0


@dataclass
class LocalLLMResponse:
    """本地 LLM 响应"""
    content: str
    success: bool
    error: Optional[str] = None


class LocalLLMClient:
    """本地 LLM 客户端（Ollama）"""

    def __init__(self, config: LocalLLMConfig = None):
        self.config = config or LocalLLMConfig()
        self._client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> bool:
        """初始化客户端"""
        if not self.config.enabled:
            logger.info("本地模型未启用")
            return False

        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
        )

        # 检查服务是否可用
        try:
            response = await self._client.get("/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                logger.info(f"Ollama 服务可用: {self.config.base_url}")
                logger.info(f"可用模型: {models}")

                # 检查目标模型是否存在
                if self.config.model_name not in models:
                    latest_name = f"{self.config.model_name}:latest" if ":" not in self.config.model_name else ""
                    if latest_name and latest_name in models:
                        logger.info(f"模型 {self.config.model_name} 使用可用标签: {latest_name}")
                        self.config.model_name = latest_name
                    else:
                        logger.warning(f"模型 {self.config.model_name} 未找到，请先拉取: ollama pull {self.config.model_name}")

                return True
        except Exception as e:
            logger.warning(f"Ollama 服务不可用: {e}")
            return False

        return False

    async def chat(
        self,
        messages: List[Dict[str, Any]],
    ) -> LocalLLMResponse:
        """
        发送聊天请求

        Args:
            messages: OpenAI 格式的消息列表

        Returns:
            LocalLLMResponse
        """
        if not self._client:
            return LocalLLMResponse(
                content="",
                success=False,
                error="客户端未初始化",
            )

        try:
            # Ollama chat API 格式
            response = await self._client.post(
                "/api/chat",
                json={
                    "model": self.config.model_name,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "num_predict": self.config.max_tokens,
                        "temperature": self.config.temperature,
                    }
                },
            )

            if response.status_code == 200:
                data = response.json()
                content = data.get("message", {}).get("content", "")
                return LocalLLMResponse(content=content.strip(), success=True)
            else:
                return LocalLLMResponse(
                    content="",
                    success=False,
                    error=f"API 错误: {response.status_code}",
                )

        except Exception as e:
            logger.error(f"Ollama 调用失败: {e}")
            return LocalLLMResponse(
                content="",
                success=False,
                error=str(e),
            )

    def chat_sync(
        self,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> LocalLLMResponse:
        """同步调用 Ollama，用于同步路由流程里的轻量兜底分类。"""
        try:
            with httpx.Client(base_url=self.config.base_url, timeout=self.config.timeout) as client:
                response = client.post(
                    "/api/chat",
                    json={
                        "model": self.config.model_name,
                        "messages": messages,
                        "stream": False,
                        "options": {
                            "num_predict": max_tokens if max_tokens is not None else self.config.max_tokens,
                            "temperature": temperature if temperature is not None else self.config.temperature,
                        },
                    },
                )

            if response.status_code == 200:
                data = response.json()
                content = data.get("message", {}).get("content", "")
                return LocalLLMResponse(content=content.strip(), success=True)
            return LocalLLMResponse(
                content="",
                success=False,
                error=f"API 错误: {response.status_code}",
            )
        except Exception as e:
            logger.error(f"Ollama 同步调用失败: {e}")
            return LocalLLMResponse(content="", success=False, error=str(e))

    async def generate(
        self,
        prompt: str,
        system: str = None,
    ) -> LocalLLMResponse:
        """
        发送生成请求（简化接口）

        Args:
            prompt: 用户提示
            system: 系统提示（可选）

        Returns:
            LocalLLMResponse
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        return await self.chat(messages)

    async def close(self):
        """关闭客户端"""
        if self._client:
            await self._client.aclose()
