"""会话管理模块 — 对话上下文管理与压缩"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy import desc
from database.models import Conversation, AgentMessage
from utils.logger_loguru import get_logger

logger = get_logger("SessionManager")

COMPRESS_PROMPT = """你是一个对话摘要器。请将以下客服对话压缩为一段简短摘要（不超过 80 字），保留关键信息：商品名称、规格、价格、买家需求、承诺事项。

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
                Conversation.status.in_(['active', 'pending_human'])
            ).order_by(desc(Conversation.created_at)).first()
            if conv:
                return conv
            conv = Conversation(
                session_id=str(uuid.uuid4()),
                shop_id=shop_id,
                buyer_id=buyer_id,
                user_id=user_id,
                status='active'
            )
            session.add(conv)
            session.flush()
            return conv

    def close_conversation(self, session_id: str):
        with self.db.session_scope() as session:
            conv = session.query(Conversation).filter(Conversation.session_id == session_id).first()
            if conv:
                conv.status = 'closed'
                conv.updated_at = datetime.now()

    def set_status(self, session_id: str, status: str):
        with self.db.session_scope() as session:
            conv = session.query(Conversation).filter(Conversation.session_id == session_id).first()
            if conv:
                conv.status = status
                conv.updated_at = datetime.now()

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
        count = self.count_messages(session_id)
        if count < 40:
            return
        messages = self.get_recent_messages(session_id, limit=40)
        old_messages = messages[:20]
        recent_messages = messages[20:]
        summary = await self._summarize_messages(old_messages)
        self._replace_with_summary(session_id, old_messages, summary)
        logger.info(f"会话 {session_id[:8]} 压缩完成: {count} -> {len(recent_messages) + 1} 条")

    async def _summarize_messages(self, messages: List[AgentMessage]) -> str:
        import requests
        text = "\n".join([
            f"{'买家' if m.role == 'user' else '客服'}: {m.content}"
            for m in messages
        ])
        payload = {
            "model": "doubao-seed-2-0-lite-260215",
            "messages": [
                {"role": "system", "content": COMPRESS_PROMPT.format(conversation_text=text)},
            ],
            "max_tokens": 80,
            "temperature": 0.3,
            "stream": False
        }
        resp = requests.post("http://127.0.0.1:11435/v1/chat/completions", json=payload, timeout=15)
        return resp.json()["choices"][0]["message"]["content"]

    def _replace_with_summary(self, session_id: str, old_messages: List[AgentMessage], summary: str):
        with self.db.session_scope() as session:
            for m in old_messages:
                session.delete(m)
            session.add(AgentMessage(session_id=session_id, role="system", content=summary, timestamp=datetime.now()))

    def build_context_messages(self, session_id: str, shop_name: str, system_prompt_template: str,
                                current_message: str, cached_products: str = "") -> List[Dict]:
        messages = self.get_recent_messages(session_id, limit=40)
        history_text = "\n".join([
            f"{'买家' if m.role == 'user' else '客服'}: {m.content[:200]}"
            for m in messages[-10:]
        ])
        system_prompt = system_prompt_template.format(
            shop_name=shop_name,
            turn_count=str(len(messages) // 2),
            cached_products=cached_products or "无"
        )
        result = [{"role": "system", "content": system_prompt}]
        if history_text:
            result.append({"role": "user", "content": f"前文摘要:\n{history_text}\n\n当前消息: {current_message}"})
        else:
            result.append({"role": "user", "content": current_message})
        return result
