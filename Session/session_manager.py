"""会话管理模块 - 对话上下文管理与压缩"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Dict, List

from sqlalchemy import desc

from core.config import (
    FALLBACK_SECOND_REMINDER_BEFORE_EXPIRY,
    PENDING_HUMAN_TTL,
    SESSION_COMPRESS_API_KEY,
    SESSION_COMPRESS_BASE_URL,
    SESSION_COMPRESS_MAX_TOKENS,
    SESSION_COMPRESS_MODEL,
    SESSION_COMPRESS_TEMPERATURE,
    SESSION_COMPRESS_TIMEOUT,
)
from database.models import AgentMessage, Conversation
from utils.logger_loguru import get_logger

logger = get_logger("SessionManager")

CONTEXT_FULL_MESSAGE_LIMIT = 20
CONTEXT_COMPRESS_OLD_COUNT = 10

COMPRESS_PROMPT = """你是一个拼多多客服对话摘要器。请将以下较早客服对话压缩为一段简短中文摘要（不超过 120 字）。
必须保留：商品名称、商品ID、规格、价格、买家明确需求、已经给过的客服边界或承诺、售后/转人工状态。
不要添加原文没有的信息。

对话记录:
{conversation_text}

摘要:"""


class SessionManager:
    def __init__(self, db_manager):
        self.db = db_manager
        self._compress_client = None

    async def get_or_create_conversation(self, shop_id: int, buyer_id: str, user_id: str = "") -> Conversation:
        with self.db.session_scope() as session:
            conv = session.query(Conversation).filter(
                Conversation.shop_id == shop_id,
                Conversation.buyer_id == buyer_id,
                Conversation.status.in_(["active", "pending_human"]),
            ).order_by(desc(Conversation.created_at)).first()
            if conv:
                if conv.status == "pending_human":
                    elapsed = (datetime.now() - conv.updated_at).total_seconds()
                    if elapsed >= PENDING_HUMAN_TTL:
                        logger.info(
                            f"会话 {conv.session_id[:8]} pending_human 已过期 "
                            f"({elapsed:.0f}s > {PENDING_HUMAN_TTL}s)，自动恢复为 active"
                        )
                        conv.status = "active"
                        conv.updated_at = datetime.now()
                return conv

            conv = Conversation(
                session_id=str(uuid.uuid4()),
                shop_id=shop_id,
                buyer_id=buyer_id,
                user_id=user_id,
                status="active",
            )
            session.add(conv)
            session.flush()
            return conv

    def close_conversation(self, session_id: str):
        with self.db.session_scope() as session:
            conv = session.query(Conversation).filter(Conversation.session_id == session_id).first()
            if conv:
                conv.status = "closed"
                conv.updated_at = datetime.now()

    def set_status(self, session_id: str, status: str):
        with self.db.session_scope() as session:
            conv = session.query(Conversation).filter(Conversation.session_id == session_id).first()
            if conv:
                conv.status = status
                conv.updated_at = datetime.now()

    def reset_session_status(self, session_id: str) -> bool:
        """手动重置会话状态为 active。"""
        with self.db.session_scope() as session:
            conv = session.query(Conversation).filter(Conversation.session_id == session_id).first()
            if conv:
                conv.status = "active"
                conv.updated_at = datetime.now()
                logger.info(f"会话 {session_id[:8]} 状态已手动重置为 active")
                return True
            return False

    def reset_all_pending_human(self, shop_id: int = None) -> int:
        """重置所有或指定店铺的 pending_human 会话为 active。"""
        with self.db.session_scope() as session:
            q = session.query(Conversation).filter(Conversation.status == "pending_human")
            if shop_id is not None:
                q = q.filter(Conversation.shop_id == shop_id)
            count = 0
            for conv in q.all():
                conv.status = "active"
                conv.updated_at = datetime.now()
                count += 1
            if count > 0:
                logger.info(f"已重置 {count} 个 pending_human 会话为 active")
            return count

    def _fallback_state_key(self, session_id: str) -> str:
        return f"session:{session_id}:fallback_state"

    def get_fallback_state(self, session_id: str) -> Dict:
        row = self.db.get_config(self._fallback_state_key(session_id))
        if not row:
            return {}
        try:
            value = row.get("config_value") or "{}"
            data = json.loads(value)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning(f"会话 {session_id[:8]} fallback 状态读取失败: {e}")
            return {}

    def should_send_fallback(self, session_id: str, now: float = None) -> str:
        """Return 'first', 'second', or '' for fallback throttling."""
        now = now or time.time()
        state = self.get_fallback_state(session_id)
        first_sent_at = float(state.get("first_sent_at") or 0)
        second_sent_at = float(state.get("second_sent_at") or 0)

        if not first_sent_at:
            return "first"
        reminder_after = max(0, PENDING_HUMAN_TTL - FALLBACK_SECOND_REMINDER_BEFORE_EXPIRY)
        if not second_sent_at and now - first_sent_at >= reminder_after:
            return "second"
        return ""

    def mark_fallback_sent(self, session_id: str, stage: str, now: float = None) -> None:
        now = now or time.time()
        state = self.get_fallback_state(session_id)
        if stage == "first":
            state["first_sent_at"] = state.get("first_sent_at") or now
        elif stage == "second":
            state["second_sent_at"] = state.get("second_sent_at") or now
        state["updated_at"] = now
        self.db.set_config(self._fallback_state_key(session_id), json.dumps(state, ensure_ascii=False))

    def next_transfer_reply_index(self, session_id: str, pool_size: int, now: float = None) -> int:
        """Persistently rotate transfer-human replies for one buyer session."""

        now = now or time.time()
        safe_pool_size = max(1, int(pool_size or 1))
        state = self.get_fallback_state(session_id)
        try:
            current = int(state.get("transfer_reply_count") or 0)
        except (TypeError, ValueError):
            current = 0
        state["transfer_reply_count"] = current + 1
        state["last_transfer_reply_at"] = now
        state["updated_at"] = now
        self.db.set_config(self._fallback_state_key(session_id), json.dumps(state, ensure_ascii=False))
        return current % safe_pool_size

    def reset_fallback_state(self, session_id: str) -> None:
        try:
            self.db.delete_config(self._fallback_state_key(session_id))
        except Exception as e:
            logger.debug(f"会话 {session_id[:8]} fallback 状态清理失败: {e}")

    def add_message(self, session_id: str, role: str, content: str):
        with self.db.session_scope() as session:
            msg = AgentMessage(session_id=session_id, role=role, content=content, timestamp=datetime.now())
            session.add(msg)

    def get_recent_messages(self, session_id: str, limit: int = 40) -> List[AgentMessage]:
        with self.db.session_scope() as session:
            return session.query(AgentMessage).filter(
                AgentMessage.session_id == session_id
            ).order_by(desc(AgentMessage.timestamp)).limit(limit).all()[::-1]

    def count_messages(self, session_id: str) -> int:
        with self.db.session_scope() as session:
            return session.query(AgentMessage).filter(AgentMessage.session_id == session_id).count()

    async def check_and_compress(self, session_id: str):
        try:
            count = self.count_messages(session_id)
        except Exception as e:
            logger.warning(f"会话 {session_id[:8]} 压缩失败，已跳过: {e}")
            return

        if count <= CONTEXT_FULL_MESSAGE_LIMIT:
            return

        messages = self.get_recent_messages(session_id, limit=max(count, CONTEXT_FULL_MESSAGE_LIMIT + CONTEXT_COMPRESS_OLD_COUNT))
        old_messages = messages[:CONTEXT_COMPRESS_OLD_COUNT]
        recent_messages = messages[CONTEXT_COMPRESS_OLD_COUNT:]
        try:
            summary = await self._summarize_messages(old_messages)
            if not summary:
                logger.warning(f"会话 {session_id[:8]} 压缩跳过: 摘要为空")
                return
            self._replace_with_summary(session_id, old_messages, summary)
            logger.info(f"会话 {session_id[:8]} 压缩完成: {count} -> {len(recent_messages) + 1} 条")
        except Exception as e:
            logger.warning(f"会话 {session_id[:8]} 压缩失败，已跳过，不影响主回复: {e}")

    async def _summarize_messages(self, messages: List[AgentMessage]) -> str:
        import requests

        text = "\n".join([
            f"{'买家' if m.role == 'user' else '客服'}: {m.content}"
            for m in messages
        ])
        payload = {
            "model": SESSION_COMPRESS_MODEL,
            "messages": [
                {"role": "system", "content": COMPRESS_PROMPT.format(conversation_text=text)},
            ],
            "max_tokens": SESSION_COMPRESS_MAX_TOKENS,
            "temperature": SESSION_COMPRESS_TEMPERATURE,
            "stream": False,
        }
        headers = {}
        if SESSION_COMPRESS_API_KEY:
            headers["Authorization"] = f"Bearer {SESSION_COMPRESS_API_KEY}"
        url = f"{SESSION_COMPRESS_BASE_URL}/v1/chat/completions"
        for attempt in range(2):
            try:
                resp = await asyncio.to_thread(
                    requests.post,
                    url,
                    json=payload,
                    headers=headers or None,
                    timeout=SESSION_COMPRESS_TIMEOUT,
                )
                if resp.status_code != 200:
                    logger.warning(f"会话压缩 HTTP {resp.status_code}: {resp.text[:200]}")
                    return ""
                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    logger.warning(f"会话压缩响应缺少 choices: {str(data)[:200]}")
                    return ""
                return choices[0].get("message", {}).get("content", "") or ""
            except requests.exceptions.Timeout:
                if attempt == 0:
                    logger.warning("会话压缩超时，重试中...")
                    continue
                raise
            except Exception as e:
                logger.warning(f"会话压缩调用失败: {e}")
                return ""

    def _replace_with_summary(self, session_id: str, old_messages: List[AgentMessage], summary: str):
        with self.db.session_scope() as session:
            for m in old_messages:
                session.delete(m)
            session.add(AgentMessage(session_id=session_id, role="system", content=summary, timestamp=datetime.now()))

    def build_context_messages(
        self,
        session_id: str,
        shop_name: str,
        system_prompt_template: str,
        current_message: str,
        cached_products: str = "",
    ) -> List[Dict]:
        messages = self.get_recent_messages(session_id, limit=40)
        history_text = "\n".join([
            f"{'买家' if m.role == 'user' else '客服'}: {m.content[:200]}"
            for m in messages[-10:]
        ])
        system_prompt = system_prompt_template.format(
            shop_name=shop_name,
            turn_count=str(len(messages) // 2),
            cached_products=cached_products or "无",
        )
        result = [{"role": "system", "content": system_prompt}]
        if history_text:
            result.append({"role": "user", "content": f"前文摘要:\n{history_text}\n\n当前消息: {current_message}"})
        else:
            result.append({"role": "user", "content": current_message})
        return result
