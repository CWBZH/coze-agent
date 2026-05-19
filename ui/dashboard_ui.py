"""首页仪表盘：多店铺状态概览。"""
from __future__ import annotations

from datetime import datetime, time as dt_time
from typing import Any, Dict, List

from PyQt6.QtWidgets import QLabel, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, StrongBodyLabel
from sqlalchemy import func

from core.connection_status import ConnectionState
from database.models import AgentMessage, Conversation, Shop
from ui.theme import BORDER, BORDER_SOFT, PRIMARY, SURFACE, TEXT, TEXT_MUTED
from utils.logger_loguru import get_logger


ACCOUNT_STATUS_TEXT = {
    1: "在线",
    2: "休息",
    3: "离线",
    4: "未验证",
    None: "未知",
}

CONNECTION_STATE_TEXT = {
    "connected": "在线",
    "connecting": "连接中",
    "reconnecting": "重连中",
    "disconnected": "已断开",
    "suspended": "已暂停",
    "error": "错误",
    "unknown": "未知",
}


def _connection_lookup(status_manager) -> Dict[tuple[str, str], Any]:
    lookup = {}
    if not status_manager:
        return lookup
    try:
        for status in status_manager.get_all_status():
            lookup[(str(status.shop_id), str(status.user_id))] = status
    except Exception:
        return {}
    return lookup


def _today_start() -> datetime:
    return datetime.combine(datetime.now().date(), dt_time.min)


def _shop_counts(db_manager, shop_db_id: int) -> Dict[str, int]:
    with db_manager.session_scope() as session:
        conversations = session.query(Conversation).filter(Conversation.shop_id == shop_db_id).count()
        transfers = (
            session.query(Conversation)
            .filter(Conversation.shop_id == shop_db_id, Conversation.status == "pending_human")
            .count()
        )
        messages = (
            session.query(func.count(AgentMessage.id))
            .join(Conversation, AgentMessage.session_id == Conversation.session_id)
            .filter(Conversation.shop_id == shop_db_id, AgentMessage.timestamp >= _today_start())
            .scalar()
            or 0
        )
        return {"conversations": conversations, "transfers": transfers, "messages": messages}


def build_dashboard_snapshot(db_manager, auto_reply_manager=None, status_manager=None) -> Dict[str, Any]:
    """Build a UI-ready dashboard snapshot from persisted and runtime state."""
    accounts = db_manager.get_all_accounts_with_details()
    connection_by_account = _connection_lookup(status_manager)
    rows: List[Dict[str, Any]] = []
    total_messages = 0
    total_transfers = 0
    online_count = 0

    for account in accounts:
        shop_id = str(account.get("shop_id") or "")
        user_id = str(account.get("user_id") or "")
        counts = _shop_counts(db_manager, _shop_db_id(db_manager, shop_id))
        status = connection_by_account.get((shop_id, user_id))
        state = status.state.value if status else "unknown"
        last_error = status.last_error if status and status.last_error else ""
        auto_reply = bool(auto_reply_manager and auto_reply_manager.is_running(account))
        online = state == ConnectionState.CONNECTED.value

        if online:
            online_count += 1
        total_messages += counts["messages"]
        total_transfers += counts["transfers"]

        rows.append(
            {
                "shop_id": shop_id,
                "name": account.get("shop_name") or shop_id,
                "account": account.get("username") or user_id,
                "account_status": ACCOUNT_STATUS_TEXT.get(account.get("status"), "未知"),
                "auto_reply": auto_reply,
                "connection_state": state,
                "online": online,
                "msgs": counts["messages"],
                "transfers": counts["transfers"],
                "conversations": counts["conversations"],
                "last_error": last_error,
            }
        )

    return {
        "stats": {
            "online": online_count,
            "total": len(accounts),
            "messages": total_messages,
            "transfers": total_transfers,
            "avg_latency": 0,
        },
        "shops": rows,
    }


def _shop_db_id(db_manager, shop_platform_id: str) -> int:
    with db_manager.session_scope() as session:
        shop = session.query(Shop).filter(Shop.shop_id == str(shop_platform_id)).first()
        return int(shop.id) if shop else 0


class DashboardWidget(QWidget):
    def __init__(self, parent=None, db_manager=None, auto_reply_manager=None, status_manager=None):
        super().__init__(parent)
        self.setObjectName("dashboard")
        self.logger = get_logger("DashboardWidget")
        self._db_manager = db_manager
        self._auto_reply_manager = auto_reply_manager
        self._status_manager = status_manager
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        cards_layout = QHBoxLayout()
        self._online_card = self._make_stat_card("在线连接", "0/0")
        self._msg_card = self._make_stat_card("今日消息", "0")
        self._transfer_card = self._make_stat_card("待人工", "0")
        self._latency_card = self._make_stat_card("AI 平均延迟", "-")
        for card in [self._online_card, self._msg_card, self._transfer_card, self._latency_card]:
            cards_layout.addWidget(card)
        layout.addLayout(cards_layout)

        self._shop_list_label = StrongBodyLabel("店铺状态")
        layout.addWidget(self._shop_list_label)
        self._shop_list = QLabel("暂无店铺数据")
        self._shop_list.setWordWrap(True)
        self._shop_list.setStyleSheet(
            f"padding: 12px; background: {SURFACE}; color: {TEXT}; "
            f"border: 1px solid {BORDER}; border-left: 5px solid {PRIMARY}; "
            "border-radius: 6px; line-height: 1.5;"
        )
        layout.addWidget(self._shop_list)
        layout.addStretch()

    def _make_stat_card(self, title: str, value: str) -> CardWidget:
        card = CardWidget()
        card.setFixedHeight(82)
        card.setStyleSheet(
            f"CardWidget {{ background-color: {SURFACE}; border: 1px solid {BORDER_SOFT}; border-radius: 8px; }}"
        )
        vl = QVBoxLayout(card)
        title_label = BodyLabel(title)
        title_label.setStyleSheet(f"color: {TEXT_MUTED}; font-weight: 600;")
        vl.addWidget(title_label)
        value_label = StrongBodyLabel(value)
        value_label.setStyleSheet(f"font-size: 24px; color: {TEXT};")
        vl.addWidget(value_label)
        return card

    def _resolve_dependencies(self):
        if self._db_manager is None:
            from database.db_manager import get_db_manager

            self._db_manager = get_db_manager()
        if self._auto_reply_manager is None:
            from ui.auto_reply.manager import auto_reply_manager

            self._auto_reply_manager = auto_reply_manager
        if self._status_manager is None:
            self._status_manager = self._get_status_manager()

    def _get_status_manager(self):
        try:
            from core.di_container import container
            from core.connection_status import ConnectionStatusManager

            if container.is_registered(ConnectionStatusManager):
                return container.get(ConnectionStatusManager)
        except Exception:
            pass
        return None

    def refresh(self):
        try:
            self._resolve_dependencies()
            snapshot = build_dashboard_snapshot(
                self._db_manager,
                self._auto_reply_manager,
                self._status_manager,
            )
            stats = snapshot["stats"]
            self.update_stats(
                stats["online"],
                stats["total"],
                messages=stats["messages"],
                transfers=stats["transfers"],
                avg_latency=stats["avg_latency"],
            )
            self.update_shop_list(snapshot["shops"])
        except Exception as e:
            self.logger.error(f"刷新首页店铺状态失败: {e}")
            self._shop_list.setText(f"店铺状态加载失败: {e}")

    def update_stats(
        self,
        online: int,
        total: int,
        messages: int = 0,
        transfers: int = 0,
        avg_latency: float = 0,
    ):
        labels = self._online_card.findChildren(StrongBodyLabel)
        if labels:
            labels[0].setText(f"{online}/{total}")
        labels = self._msg_card.findChildren(StrongBodyLabel)
        if labels:
            labels[0].setText(str(messages))
        labels = self._transfer_card.findChildren(StrongBodyLabel)
        if labels:
            labels[0].setText(str(transfers))
        labels = self._latency_card.findChildren(StrongBodyLabel)
        if labels:
            labels[0].setText(f"{avg_latency:.1f}s" if avg_latency > 0 else "-")

    def update_shop_list(self, shops: list):
        lines = []
        for shop in shops:
            dot = "●"
            state = shop.get("connection_state", "unknown")
            status = CONNECTION_STATE_TEXT.get(state, state)
            auto_reply = "运行中" if shop.get("auto_reply") else "未运行"
            error = f" | 错误: {shop['last_error']}" if shop.get("last_error") else ""
            lines.append(
                f"{dot} {shop['name']} ({shop['shop_id']}) | 账号: {shop['account']} | "
                f"账号状态: {shop['account_status']} | 连接: {status} | 自动回复: {auto_reply} | "
                f"会话: {shop.get('conversations', 0)} | 今日消息: {shop.get('msgs', 0)} | "
                f"待人工: {shop.get('transfers', 0)}{error}"
            )
        self._shop_list.setText("\n".join(lines) or "暂无店铺数据")
