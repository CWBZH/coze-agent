"""首页仪表盘 — 多店铺概览"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from qfluentwidgets import StrongBodyLabel, BodyLabel, CardWidget


class DashboardWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dashboard")
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 统计卡片行
        cards_layout = QHBoxLayout()
        self._online_card = self._make_stat_card("在线店铺", "0/0")
        self._msg_card = self._make_stat_card("今日消息", "0")
        self._transfer_card = self._make_stat_card("转人工", "0")
        self._latency_card = self._make_stat_card("AI 平均延迟", "-")
        for card in [self._online_card, self._msg_card, self._transfer_card, self._latency_card]:
            cards_layout.addWidget(card)
        layout.addLayout(cards_layout)

        # 店铺列表
        self._shop_list_label = StrongBodyLabel("店铺状态")
        layout.addWidget(self._shop_list_label)
        self._shop_list = QLabel("暂无店铺数据")
        self._shop_list.setWordWrap(True)
        self._shop_list.setStyleSheet("padding: 10px; background: #f5f5f5; border-radius: 6px;")
        layout.addWidget(self._shop_list)
        layout.addStretch()

    def _make_stat_card(self, title: str, value: str) -> CardWidget:
        card = CardWidget()
        card.setFixedHeight(80)
        vl = QVBoxLayout(card)
        title_label = BodyLabel(title)
        title_label.setStyleSheet("color: #666;")
        vl.addWidget(title_label)
        value_label = StrongBodyLabel(value)
        value_label.setStyleSheet("font-size: 24px;")
        vl.addWidget(value_label)
        return card

    def update_stats(self, online: int, total: int, messages: int = 0,
                     transfers: int = 0, avg_latency: float = 0):
        labels = self._online_card.findChildren(StrongBodyLabel)
        if len(labels) > 0:
            labels[0].setText(f"{online}/{total}")
        labels = self._msg_card.findChildren(StrongBodyLabel)
        if len(labels) > 0:
            labels[0].setText(str(messages))
        labels = self._transfer_card.findChildren(StrongBodyLabel)
        if len(labels) > 0:
            labels[0].setText(str(transfers))
        if avg_latency > 0:
            labels = self._latency_card.findChildren(StrongBodyLabel)
            if len(labels) > 0:
                labels[0].setText(f"{avg_latency:.1f}s")

    def update_shop_list(self, shops: list):
        text = "\n".join([
            f"{'🟢' if s.get('online') else '🔴'} {s['name']}  消息:{s.get('msgs', 0)}  转人工:{s.get('transfers', 0)}"
            for s in shops
        ])
        self._shop_list.setText(text or "暂无店铺数据")
