"""Build human-transfer alert context from local database."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import desc

from database.models import Account, AgentMessage, Conversation, Shop
from utils.logger_loguru import get_logger

logger = get_logger("HumanAlertContext")


@dataclass
class HumanAlertContext:
    shop_id: str
    shop_name: str = ""
    account_name: str = ""
    buyer_id: str = ""
    session_id: str = ""
    session_status: str = ""
    latest_user_message: str = ""
    latest_assistant_message: str = ""


class HumanAlertContextBuilder:
    def __init__(self, db_manager):
        self.db = db_manager

    def build(self, shop_platform_id: str, buyer_id: str) -> HumanAlertContext:
        context = HumanAlertContext(shop_id=str(shop_platform_id), buyer_id=str(buyer_id))
        try:
            with self.db.session_scope() as session:
                shop = session.query(Shop).filter(Shop.shop_id == str(shop_platform_id)).first()
                if not shop:
                    return context

                context.shop_name = shop.shop_name or ""
                account = session.query(Account).filter(Account.shop_id == shop.id).first()
                if account:
                    context.account_name = account.username or ""

                conv = session.query(Conversation).filter(
                    Conversation.shop_id == shop.id,
                    Conversation.buyer_id == str(buyer_id),
                ).order_by(desc(Conversation.updated_at)).first()
                if not conv:
                    return context

                context.session_id = conv.session_id
                context.session_status = conv.status or ""
                context.latest_user_message = self._latest_message(session, conv.session_id, "user")
                context.latest_assistant_message = self._latest_message(session, conv.session_id, "assistant")
                return context
        except Exception as e:
            logger.warning(f"构建转人工通知上下文失败: shop_id={shop_platform_id}, buyer_id={buyer_id}, error={e}")
            return context

    def _latest_message(self, session, session_id: str, role: str) -> str:
        row: Optional[AgentMessage] = session.query(AgentMessage).filter(
            AgentMessage.session_id == session_id,
            AgentMessage.role == role,
        ).order_by(desc(AgentMessage.timestamp)).first()
        if not row or not row.content:
            return ""
        return str(row.content)[:500]


def format_human_alert_message(
    alert_context: HumanAlertContext,
    reason: str,
    alert_level: str,
    now: Optional[datetime] = None,
) -> str:
    now = now or datetime.now()
    level_label = "高危" if alert_level == "high" else "普通"
    shop_label = alert_context.shop_name or "未知店铺"
    account_label = alert_context.account_name or "未知账号"
    latest_user_message = alert_context.latest_user_message or "无"
    latest_assistant_message = alert_context.latest_assistant_message or "无"
    session_status = alert_context.session_status or "未知"

    return "\n".join(
        [
            "【客服助手转人工提醒】",
            f"店铺：{shop_label}（{alert_context.shop_id}）",
            f"账号：{account_label}",
            f"买家：{alert_context.buyer_id}",
            f"等级：{level_label}",
            f"原因：{reason}",
            "",
            "最新买家消息：",
            latest_user_message,
            "",
            "最近系统回复：",
            latest_assistant_message,
            "",
            f"会话状态：{session_status}",
            f"时间：{now.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "请尽快进入客服助手处理。",
        ]
    )
