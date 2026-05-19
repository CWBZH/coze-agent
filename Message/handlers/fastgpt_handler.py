"""FastGPT API 调用处理器。"""
import random
from typing import Dict, List

import requests

from core.constants import TRANSFER_HUMAN_REPLY
from utils.logger_loguru import get_logger

logger = get_logger("FastGPTHandler")

SYSTEM_PROMPT_TEMPLATE = """你是拼多多店铺【{shop_name}】的客服。

## 行为准则
1. 回答亲切、专业、简洁，不超过 80 字。
2. 严禁编造退款、赔偿、包邮承诺。除非知识库明确说明。
3. 如果不确定，回复"我帮您确认一下，稍等哦~"。
4. 买家要求退款/投诉/差评时，回复必须包含"转人工"关键词。
5. 严禁暴露你是 AI，不要说"作为语言模型"。

## 当前信息
- 店铺: {shop_name}
- 对话轮次: 第 {turn_count} 轮
- 已有商品缓存: {cached_products}"""

FALLBACK_POOL = [
    "亲，我正在为您查询，请稍等片刻~",
    "亲，我正在核实信息，马上就好~",
    "亲，稍等一下，客服正在为您处理哦~",
    "亲，正在加急为您查询中~",
    "亲，信息正在赶来，请稍等~",
    "亲，已经收到您的消息，马上回复您~",
]
FALLBACK_HARD = TRANSFER_HUMAN_REPLY


class FastGPTHandler:
    def __init__(
        self,
        fastgpt_url: str = "http://localhost:3000/api",
        api_key: str = "",
        timeout: int = 25,
        max_retries: int = 1,
    ):
        self.fastgpt_url = fastgpt_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self._session_failures: Dict[str, int] = {}

    def call(
        self,
        messages: List[Dict],
        dataset_id: str,
        chat_id: str = "",
        shop_id: str = "",
        shop_name: str = "",
        temperature: float = 0.7,
        max_tokens: int = 120,
    ) -> Dict:
        if not dataset_id:
            logger.error(f"FastGPT dataset missing: shop_id={shop_id}, shop_name={shop_name}, chat_id={chat_id}")
            return {"success": False, "content": None, "error": "missing_dataset_id"}

        url = f"{self.fastgpt_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": "doubao-seed-2-0-lite-260215",
            "messages": messages,
            "datasetId": dataset_id,
            "chatId": chat_id,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        logger.info(
            f"[FastGPTRoute] shop_id={shop_id}, shop_name={shop_name}, "
            f"dataset_id={dataset_id}, chat_id={chat_id}"
        )
        for attempt in range(self.max_retries + 1):
            try:
                logger.debug(f"FastGPT call attempt={attempt + 1}")
                resp = requests.post(url, json=payload, timeout=self.timeout, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    content = (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "")
                    usage = data.get("usage", {})
                    return {"success": True, "content": content, "tokens": usage.get("total_tokens", 0)}
                logger.error(f"FastGPT HTTP {resp.status_code}: {resp.text[:200]}")
                return {"success": False, "content": None, "error": f"HTTP {resp.status_code}"}
            except requests.exceptions.Timeout:
                logger.error(f"FastGPT timeout attempt={attempt + 1}")
                if attempt < self.max_retries:
                    continue
                return {"success": False, "content": None, "error": "timeout"}
            except Exception as e:
                logger.error(f"FastGPT error: {e}")
                return {"success": False, "content": None, "error": str(e)}
        return {"success": False, "content": None, "error": "max_retries_exceeded"}

    def get_fallback(self, session_id: str, max_failures: int = 3, already_failed: bool = False) -> str:
        if not already_failed:
            return random.choice(FALLBACK_POOL)
        count = self._session_failures.get(session_id, 0) + 1
        self._session_failures[session_id] = count
        if count >= max_failures:
            return FALLBACK_HARD
        return random.choice(FALLBACK_POOL)

    def should_transfer(self, session_id: str, max_failures: int = 3) -> bool:
        return self._session_failures.get(session_id, 0) >= max_failures

    def reset_failures(self, session_id: str):
        self._session_failures.pop(session_id, None)

    def contains_transfer_intent(self, reply_text: str) -> bool:
        keywords = ["转人工", "人工客服", "投诉处理", "维权"]
        return any(kw in reply_text for kw in keywords)
