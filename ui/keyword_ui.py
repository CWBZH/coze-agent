"""关键词管理界面 - Level-1 静态规则拦截器。"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TableWidget,
    TextEdit,
)
from PyQt6.QtWidgets import QHeaderView, QTableWidgetItem

from database.db_manager import get_db_manager
from database.redis_manager import redis_manager
from utils.logger_loguru import get_logger

logger = get_logger("KeywordUI")


class KeywordTableWidget(TableWidget):
    edit_clicked = pyqtSignal(str, str)
    delete_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHorizontalHeaderLabels(["触发关键词组", "固定回复内容", "操作"])
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(0, 260)
        self.setColumnWidth(2, 220)
        self.verticalHeader().setDefaultSectionSize(50)

    def addRule(self, keyword: str, reply: str):
        row = self.rowCount()
        self.insertRow(row)

        keyword_item = QTableWidgetItem(keyword)
        keyword_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self.setItem(row, 0, keyword_item)

        reply_item = QTableWidgetItem(reply)
        reply_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self.setItem(row, 1, reply_item)

        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(6)

        edit_btn = PushButton("编辑")
        edit_btn.setIcon(FIF.EDIT)
        edit_btn.clicked.connect(lambda: self.edit_clicked.emit(keyword, reply))

        delete_btn = PushButton("删除")
        delete_btn.setIcon(FIF.DELETE)
        delete_btn.clicked.connect(lambda: self.delete_clicked.emit(keyword))

        action_layout.addWidget(edit_btn)
        action_layout.addWidget(delete_btn)
        self.setCellWidget(row, 2, action_widget)

    def clearTable(self):
        self.setRowCount(0)


class RuleEditDialog(QDialog):
    def __init__(self, keyword: str = "", reply: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑静态规则")
        self.setFixedSize(560, 340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        form_layout = QFormLayout()
        form_layout.setSpacing(12)

        self.keyword_edit = LineEdit()
        self.keyword_edit.setPlaceholderText("例如：发什么快递 / 什么快递 / 快递公司")
        self.keyword_edit.setText(keyword)
        self.keyword_edit.setClearButtonEnabled(True)
        form_layout.addRow("触发关键词组:", self.keyword_edit)

        self.reply_edit = TextEdit()
        self.reply_edit.setPlaceholderText("例如：亲，我们默认发极兔速递哦。")
        self.reply_edit.setPlainText(reply)
        form_layout.addRow("固定回复:", self.reply_edit)

        layout.addLayout(form_layout)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        cancel_btn = PushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        save_btn = PrimaryPushButton("保存")
        save_btn.clicked.connect(self.accept)
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(save_btn)
        layout.addLayout(button_layout)

    def getValues(self):
        return self.keyword_edit.text().strip(), self.reply_edit.toPlainText().strip()


class KeywordManagerWidget(QWidget):
    """静态规则管理主界面。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = get_db_manager()
        self.current_shop_id: str = self._resolve_default_shop_id() or "default"
        self.setupUI()
        self.loadRules()

    def _resolve_default_shop_id(self) -> Optional[str]:
        shops = self.db.get_shops("pinduoduo")
        if not shops:
            return None
        return str(shops[0]["shop_id"])

    def setupUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(18)

        header_layout = QHBoxLayout()
        title_area = QVBoxLayout()
        title_area.addWidget(SubtitleLabel("静态规则管理 (Level-1 拦截器)"))
        self.stats_label = CaptionLabel("共 0 条规则")
        title_area.addWidget(self.stats_label)
        header_layout.addLayout(title_area)
        header_layout.addStretch()

        self.import_btn = PushButton("批量导入")
        self.import_btn.setIcon(FIF.FOLDER_ADD)
        self.import_btn.clicked.connect(self.onImportRules)
        self.add_btn = PrimaryPushButton("添加规则")
        self.add_btn.setIcon(FIF.ADD)
        self.add_btn.clicked.connect(self.onAddRule)
        header_layout.addWidget(self.import_btn)
        header_layout.addWidget(self.add_btn)
        main_layout.addLayout(header_layout)

        hint = CaptionLabel(
            "保存后立即生效。关键词组可用 / 、逗号、分号或换行分隔；命中任意词后直接返回固定回复，不进入 AI。"
        )
        main_layout.addWidget(hint)

        self.table_widget = KeywordTableWidget()
        self.table_widget.edit_clicked.connect(self.onEditRule)
        self.table_widget.delete_clicked.connect(self.onDeleteRule)
        main_layout.addWidget(self.table_widget, 1)
        self.setObjectName("静态规则管理")

    def loadRules(self):
        try:
            rules = redis_manager.get_static_rules(self.current_shop_id)
            self.refreshRuleList(rules)
        except Exception as e:
            logger.error(f"加载静态规则失败: {e}")
            InfoBar.error(title="加载失败", content=str(e), duration=3000, parent=self)

    def refreshRuleList(self, rules: dict):
        self.table_widget.clearTable()
        for keyword, reply in rules.items():
            self.table_widget.addRule(keyword, reply)
        self.stats_label.setText(f"共 {len(rules)} 条规则")

    def onAddRule(self):
        dialog = RuleEditDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            keyword, reply = dialog.getValues()
            self._saveRule(keyword, reply)

    def onEditRule(self, keyword: str, reply: str):
        dialog = RuleEditDialog(keyword=keyword, reply=reply, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_keyword, new_reply = dialog.getValues()
            if new_keyword != keyword:
                redis_manager.delete_static_rule(self.current_shop_id, keyword)
            self._saveRule(new_keyword, new_reply, success_text="规则已更新")

    def _saveRule(self, keyword: str, reply: str, success_text: str = "规则已保存"):
        if not keyword or not reply:
            InfoBar.warning(title="输入无效", content="触发关键词组和固定回复都不能为空", duration=2000, parent=self)
            return
        if redis_manager.set_static_rule(self.current_shop_id, keyword, reply):
            InfoBar.success(
                title="保存成功",
                content=success_text,
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            self.loadRules()
        else:
            InfoBar.error(title="保存失败", content="无法保存静态规则", duration=2000, parent=self)

    def onDeleteRule(self, keyword: str):
        reply = QMessageBox.question(
            self,
            "确认删除",
            f'确定要删除规则 "{keyword}" 吗？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if redis_manager.delete_static_rule(self.current_shop_id, keyword):
                InfoBar.success(title="删除成功", content=f"规则 '{keyword}' 已删除", duration=2000, parent=self)
                self.loadRules()

    def onImportRules(self):
        InfoBar.info(title="暂未开放", content="批量导入后续再接入，目前请逐条添加。", duration=2000, parent=self)

    def reloadRules(self):
        self.loadRules()
