"""PushPlus external notification client."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
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


def _response_summary(text: str) -> tuple[int, str]:
    text = "" if text is None else str(text)
    return len(text), hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


class PushPlusNotifier:
    """Small wrapper around PushPlus send API."""

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
            text = resp.text or ""
            response_length, response_hash = _response_summary(text)
            if resp.status_code != 200:
                logger.warning(
                    "event=pushplus.response.failed "
                    f"status_code={resp.status_code} response_length={response_length} "
                    f"response_hash={response_hash}"
                )
                return PushPlusResult(
                    sent=False,
                    reason=f"http_{resp.status_code}",
                    response_code=resp.status_code,
                    response_text="",
                )

            data: Dict = {}
            try:
                data = resp.json()
            except Exception:
                logger.warning(
                    "event=pushplus.response.invalid_json "
                    f"status_code={resp.status_code} response_length={response_length} "
                    f"response_hash={response_hash}"
                )

            code = data.get("code") if isinstance(data, dict) else None
            if code == 200:
                logger.info(
                    "event=pushplus.response.accepted "
                    f"status_code={resp.status_code} provider_code={code} "
                    f"response_length={response_length} response_hash={response_hash}"
                )
                return PushPlusResult(sent=True, response_code=resp.status_code, response_text="")

            logger.warning(
                "event=pushplus.response.rejected "
                f"status_code={resp.status_code} provider_code={code} "
                f"response_length={response_length} response_hash={response_hash}"
            )
            return PushPlusResult(
                sent=False,
                reason=f"code_{code}",
                response_code=resp.status_code,
                response_text="",
            )
        except Exception as e:
            logger.warning(f"event=pushplus.response.exception error_type={type(e).__name__}")
            return PushPlusResult(sent=False, reason=type(e).__name__)
