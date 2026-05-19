"""pushplus external notification client."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Optional

import requests

from core.config import (
    PUSHPLUS_CHANNEL,
    PUSHPLUS_ENABLED,
    PUSHPLUS_TEMPLATE,
    PUSHPLUS_TIMEOUT,
    PUSHPLUS_TOKEN,
)
from utils.logger_loguru import get_logger

logger = get_logger("PushPlusNotifier")


@dataclass
class PushPlusResult:
    sent: bool
    skipped: bool = False
    reason: str = ""
    response_code: Optional[int] = None
    response_text: str = ""


class PushPlusNotifier:
    """Small wrapper around pushplus send API."""

    def __init__(
        self,
        enabled: bool = PUSHPLUS_ENABLED,
        token: str = PUSHPLUS_TOKEN,
        channel: str = PUSHPLUS_CHANNEL,
        template: str = PUSHPLUS_TEMPLATE,
        timeout: int = PUSHPLUS_TIMEOUT,
        endpoint: str = "http://www.pushplus.plus/send",
    ):
        self.enabled = enabled
        self.token = token.strip()
        self.channel = channel
        self.template = template
        self.timeout = timeout
        self.endpoint = endpoint

    def send(self, title: str, content: str) -> PushPlusResult:
        if not self.enabled:
            return PushPlusResult(sent=False, skipped=True, reason="disabled")
        if not self.token:
            return PushPlusResult(sent=False, skipped=True, reason="missing_token")

        payload = {
            "token": self.token,
            "title": title,
            "content": content,
            "template": self.template,
            "channel": self.channel,
        }
        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            resp = requests.post(
                self.endpoint,
                data=body,
                timeout=self.timeout,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            text = resp.text[:500]
            if resp.status_code != 200:
                logger.warning(f"pushplus HTTP {resp.status_code}: {text}")
                return PushPlusResult(
                    sent=False,
                    reason=f"http_{resp.status_code}",
                    response_code=resp.status_code,
                    response_text=text,
                )

            data: Dict = {}
            try:
                data = resp.json()
            except Exception:
                logger.warning(f"pushplus 响应不是 JSON: {text}")

            code = data.get("code") if isinstance(data, dict) else None
            if code == 200:
                logger.info(f"pushplus 请求已受理: {data.get('data')}")
                return PushPlusResult(sent=True, response_code=resp.status_code, response_text=text)

            logger.warning(f"pushplus 请求未受理: {text}")
            return PushPlusResult(
                sent=False,
                reason=f"code_{code}",
                response_code=resp.status_code,
                response_text=text,
            )
        except Exception as e:
            logger.warning(f"pushplus 发送失败: {e}")
            return PushPlusResult(sent=False, reason=str(e))
