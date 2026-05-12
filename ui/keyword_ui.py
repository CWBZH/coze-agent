# 关键词管理界面 - V2.0 静态规则拦截器重构版
#
# 功能升级：
# - 触发词 + 固定回复 成对配置
# - Redis Hash 存储，支持热更新
# - Level -1 零算力路由拦截

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QVBoxLayout, QWidget, QLabel,
                            QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
                            QDialog, QFormLayout, QLineEdit, QMessageBox, QStackedWidget)
from PyQt6.QtGui import QFont, QIcon
from qfluentwidgets import (SubtitleLabel, CaptionLabel, BodyLabel,
                           PrimaryPushButton, PushButton, CardWidget,
                           ScrollArea, FluentIcon as FIF,
                           TableWidget, LineEdit, TextEdit, InfoBar, InfoBarPosition,
                           SegmentedWidget)
from core.config_manager import config_manager
from database.redis_manager import redis_manager
from utils.logger_loguru import get_logger

logger = get_logger("KeywordUI")


class KeywordTableWidget(TableWidget):
    """关键词表格组件 - 支持触发词+回复双列展示"""

    # 定义信号
    edit_clicked = pyqtSignal(str, str)  # 编辑按钮点击信号，传递 (关键词, 回复)
    delete_clicked = pyqtSignal(str)  # 删除按钮点击信号，传递关键词

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupTable()

    def setupTable(self):
        """设置表格"""
        # 设置列数和表头（新增"固定回复"列）
        self.setColumnCount(3)
        self.setHorizontalHeaderLabels(['触发关键词', '固定回复内容', '操作'])

        # 设置表格属性
        self.setAlternatingRowColors(True)  # 交替行颜色
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)  # 选择整行
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)  # 单选
        self.verticalHeader().setVisible(False)  # 隐藏行号

        # 设置列宽
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # 关键词列
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # 回复列自动拉伸
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)   # 操作列固定宽度

        self.setColumnWidth(0, 200)  # 关键词列
        self.setColumnWidth(2, 250)  # 操作列

        # 设置行高
        self.verticalHeader().setDefaultSectionSize(50)

    def addRule(self, keyword: str, reply: str):
        """添加规则到表格（关键词+回复）"""
        row = self.rowCount()
        self.insertRow(row)

        # 关键词
        keyword_item = QTableWidgetItem(keyword)
        keyword_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self.setItem(row, 0, keyword_item)

        # 固定回复
        reply_item = QTableWidgetItem(reply)
        reply_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self.setItem(row, 1, reply_item)

        # 操作按钮
        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(5, 5, 5, 5)
        action_layout.setSpacing(5)
        action_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 编辑按钮
        edit_btn = PushButton("编辑")
        edit_btn.setIcon(FIF.EDIT)
        edit_btn.setFixedSize(100, 30)
        edit_btn.clicked.connect(lambda: self.edit_clicked.emit(keyword, reply))

        # 删除按钮
        delete_btn = PushButton("删除")
        delete_btn.setIcon(FIF.DELETE)
        delete_btn.setFixedSize(100, 30)
        delete_btn.clicked.connect(lambda: self.delete_clicked.emit(keyword))

        action_layout.addWidget(edit_btn)
        action_layout.addWidget(delete_btn)
        self.setCellWidget(row, 2, action_widget)

    def clearTable(self):
        """清空表格"""
        self.setRowCount(0)


class RuleEditDialog(QDialog):
    """规则编辑对话框 - 支持触发词+回复成对编辑"""

    def __init__(self, keyword="", reply="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑静态规则")
        self.setFixedSize(500, 300)
        self.setupUI(keyword, reply)

    def setupUI(self, keyword: str, reply: str):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        # 表单布局
        form_layout = QFormLayout()
        form_layout.setSpacing(15)

        # 触发关键词输入框
        self.keyword_edit = LineEdit()
        self.keyword_edit.setPlaceholderText("例如：发什么快递 / 什么快递 / 快递公司")
        self.keyword_edit.setText(keyword)
        self.keyword_edit.setClearButtonEnabled(True)
        form_layout.addRow("触发关键词组:", self.keyword_edit)

        # 固定回复输入框
        self.reply_edit = TextEdit()
        self.reply_edit.setPlaceholderText("例如：默认发顺丰快递，部分地区可能发其他快递")
        self.reply_edit.setText(reply)
        self.reply_edit.setMaximumHeight(120)
        form_layout.addRow("固定回复:", self.reply_edit)

        layout.addLayout(form_layout)

        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        save_btn = PrimaryPushButton("保存")
        save_btn.setFixedSize(100, 35)
        save_btn.clicked.connect(self.accept)

        cancel_btn = PushButton("取消")
        cancel_btn.setFixedSize(100, 35)
        cancel_btn.clicked.connect(self.reject)

        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def getValues(self) -> tuple:
        """获取输入的值"""
        return (
            self.keyword_edit.text().strip(),
            self.reply_edit.toPlainText().strip()
        )


class ConfigFieldCard(CardWidget):
    """带完整说明的配置输入卡片。"""

    def __init__(
        self,
        title: str,
        route_text: str,
        behavior_text: str,
        field_text: str,
        multiline: bool = True,
        placeholder: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.multiline = multiline
        self.setupUI(title, route_text, behavior_text, field_text, placeholder)
        self.setStyleSheet("""
            ConfigFieldCard {
                background-color: #ffffff;
                border: 1px solid #d9dde3;
                border-radius: 8px;
            }
            ConfigFieldCard:focus,
            ConfigFieldCard:hover {
                background-color: #ffffff;
                border: 1px solid #cfd5dd;
            }
        """)

    def setupUI(self, title: str, route_text: str, behavior_text: str, field_text: str, placeholder: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title_label = BodyLabel(title)
        title_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #111827;")
        layout.addWidget(title_label)

        for text in (route_text, behavior_text, field_text):
            label = CaptionLabel(text)
            label.setWordWrap(True)
            label.setStyleSheet("color: #1f2937; font-size: 12px;")
            layout.addWidget(label)

        if self.multiline:
            self.edit = TextEdit()
            self.edit.setMaximumHeight(112)
            self.edit.setPlaceholderText(placeholder)
        else:
            self.edit = LineEdit()
            self.edit.setPlaceholderText(placeholder)
        self.edit.setStyleSheet("""
            TextEdit, LineEdit {
                color: #111827;
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
            }
            TextEdit:focus, LineEdit:focus {
                color: #111827;
                background-color: #ffffff;
                border: 1px solid #2563eb;
            }
        """)
        layout.addWidget(self.edit)

    def value(self):
        if self.multiline:
            return [line.strip() for line in self.edit.toPlainText().splitlines() if line.strip()]
        return self.edit.text().strip()

    def setValue(self, value):
        if self.multiline:
            if isinstance(value, list):
                self.edit.setPlainText("\n".join(value))
            else:
                self.edit.setPlainText(str(value or ""))
        else:
            self.edit.setText(str(value or ""))


class ReplyRulesPanel(QWidget):
    """一级拦截和模板话术配置，放在关键词管理页统一维护。"""

    def __init__(self, shop_id: str = "default", parent=None):
        super().__init__(parent)
        self.shop_id = shop_id
        self.setupUI()
        self.loadRules()

    def setupUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        title_area = QWidget()
        title_layout = QVBoxLayout(title_area)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(4)
        title_layout.addWidget(SubtitleLabel("一级拦截话术"))
        title_layout.addWidget(CaptionLabel("左侧标明触发场景和配置键；右侧填写实际回复或触发词。"))

        self.save_btn = PrimaryPushButton("保存话术")
        self.save_btn.setIcon(FIF.SAVE)
        self.save_btn.setFixedSize(120, 36)
        self.save_btn.clicked.connect(self.saveRules)

        header_layout.addWidget(title_area)
        header_layout.addStretch()
        header_layout.addWidget(self.save_btn)
        layout.addWidget(header)
        self.cards = {}

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        cards_layout = QVBoxLayout(container)
        cards_layout.setContentsMargins(2, 2, 10, 2)
        cards_layout.setSpacing(12)

        card_specs = [
            (
                "general_reply",
                "短句/闲聊默认回复",
                "触发路由：general 通用回复",
                "什么时候用：用户发“好吧、嗯、在吗、？”这类短句，或消息太短且没有商品词时。",
                "关联关系：下面“短句触发词 short_default_phrases”命中后，会直接使用这句回复。",
                False,
                "例如：在的，您想咨询哪方面呢？",
            ),
            (
                "short_default_phrases",
                "短句触发词",
                "触发路由：general 通用回复",
                "什么时候用：用户消息完全等于这里的任意一行。",
                "关联关系：命中这些词后，回复上面的 general_reply。",
                True,
                "每行一个：好吧\n嗯\n在吗\n？",
            ),
            (
                "unknown_reply",
                "未知意图回复",
                "触发路由：unknown 未识别",
                "什么时候用：路由没有命中售前、售后、推荐、物流、人工等任何分类。",
                "关联关系：这是 unknown 路由的兜底话术。",
                False,
                "例如：您想看哪类产品？香氛、湿敷棉、洗脸巾都可以说一下。",
            ),
            (
                "logistics_reply",
                "物流默认回复",
                "触发路由：logistics 物流咨询",
                "什么时候用：用户问发货、快递、几天到，但系统没有更具体物流数据时。",
                "关联关系：物流关键词命中后，若无订单物流详情，使用这句回复。",
                False,
                "例如：正常48小时内发货，具体到达以物流为准哦。",
            ),
            (
                "no_product_match_reply",
                "商品未匹配回复",
                "触发路由：recommend/pre_sale 商品检索",
                "什么时候用：用户想找商品或让推荐，但关键词没有召回到有效商品。",
                "关联关系：商品召回失败时使用这句，不再编造商品。",
                False,
                "例如：暂时没找到完全对应的款式，可以换个关键词我再帮您看～",
            ),
            (
                "child_age_terms",
                "年龄/人群触发词",
                "触发路由：pre_sale 商品属性追问",
                "什么时候用：用户问“小孩能用吗、12岁能用吗、孕妇能用吗”等。",
                "关联关系：命中这些词后，先查商品知识；查到年龄用 child_known_age，查不到用 child_unknown_age。",
                True,
                "每行一个：岁\n12岁\n小孩\n儿童\n孕妇\n能用",
            ),
            (
                "child_known_age_reply_template",
                "年龄已知回复模板",
                "触发路由：pre_sale 商品属性追问",
                "什么时候用：商品知识里能提取出适用年龄，例如“十二岁以上就能用”。",
                "关联关系：必须保留 {age}，系统会把商品里的年龄信息填进去。",
                False,
                "例如：这款适用年龄是{age}，建议按页面说明使用哦。",
            ),
            (
                "child_unknown_age_reply",
                "年龄未知回复",
                "触发路由：pre_sale 商品属性追问",
                "什么时候用：用户问年龄/人群，但商品知识里没有明确适用年龄。",
                "关联关系：child_age_terms 命中但找不到年龄信息时，使用这句回复。",
                False,
                "例如：商品信息里没有明确标注儿童适用，建议先按页面说明确认后再用哦。",
            ),
        ]

        for key, title, route, behavior, field, multiline, placeholder in card_specs:
            card = ConfigFieldCard(title, route, behavior, field, multiline, placeholder)
            self.cards[key] = card
            cards_layout.addWidget(card)

        cards_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

    def loadRules(self):
        rules = config_manager.get_agent_reply_rules(self.shop_id)
        for key, card in self.cards.items():
            card.setValue(rules.get(key, [] if card.multiline else ""))

    def collectRules(self) -> dict:
        return {key: card.value() for key, card in self.cards.items()}

    def saveRules(self):
        if config_manager.set_agent_reply_rules(self.collectRules(), self.shop_id):
            InfoBar.success(
                title="保存成功",
                content="一级拦截话术已保存",
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        else:
            InfoBar.error(
                title="保存失败",
                content="无法保存一级拦截话术",
                duration=2000,
                parent=self,
            )

class RouteKeywordsPanel(QWidget):
    """路由关键词配置面板。"""

    ROUTE_FIELDS = [
        ("redline", "高危红线", "路由名：redline", "命中后：强制转人工，触发 high 警报。", "例子：投诉、过敏、假货、12315"),
        ("human_request", "主动请求人工", "路由名：human_request", "命中后：普通转人工，触发 low 警报。", "例子：转人工、人工客服、找客服"),
        ("after_sales", "售后问题", "路由名：after_sales", "命中后：走售后知识/售后模板，不推荐商品。", "例子：退款、退货、没效果、没味道、破损"),
        ("pre_sale", "售前咨询", "路由名：pre_sale", "命中后：优先检索商品知识，回答属性/价格/用法。", "例子：价格、成分、规格、怎么用"),
        ("recommend", "推荐导购", "路由名：recommend", "命中后：走商品推荐召回，给用户推荐 SKU。", "例子：推荐、哪个好、想买、想看"),
        ("logistics", "物流咨询", "路由名：logistics", "命中后：走物流知识或物流兜底话术。", "例子：快递、物流、发货、几天能到"),
    ]

    def __init__(self, shop_id: str = "default", parent=None):
        super().__init__(parent)
        self.shop_id = shop_id
        self.edits = {}
        self.setupUI()
        self.loadKeywords()

    def setupUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        title_area = QWidget()
        title_layout = QVBoxLayout(title_area)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(4)
        title_layout.addWidget(SubtitleLabel("路由关键词"))
        title_layout.addWidget(CaptionLabel("左侧是实际路由名和命中后的处理方向；右侧每行一个关键词。保存后重启或重新初始化自动回复生效。"))

        self.save_btn = PrimaryPushButton("保存路由")
        self.save_btn.setIcon(FIF.SAVE)
        self.save_btn.setFixedSize(120, 36)
        self.save_btn.clicked.connect(self.saveKeywords)

        header_layout.addWidget(title_area)
        header_layout.addStretch()
        header_layout.addWidget(self.save_btn)
        layout.addWidget(header)

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        cards_layout = QVBoxLayout(container)
        cards_layout.setContentsMargins(2, 2, 10, 2)
        cards_layout.setSpacing(12)

        for key, title, route, behavior, examples in self.ROUTE_FIELDS:
            card = ConfigFieldCard(
                title=title,
                route_text=route,
                behavior_text=behavior,
                field_text="关键词配置：每行一个词；用户消息包含任意一行时命中该路由。",
                multiline=True,
                placeholder=examples,
            )
            self.edits[key] = card
            cards_layout.addWidget(card)

        cards_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

    def loadKeywords(self):
        keywords = config_manager.get_route_keywords(self.shop_id)
        for key, card in self.edits.items():
            card.setValue(keywords.get(key, []))

    def collectKeywords(self) -> dict:
        return {key: card.value() for key, card in self.edits.items()}

    def saveKeywords(self):
        if config_manager.set_route_keywords(self.collectKeywords(), self.shop_id):
            InfoBar.success(
                title="保存成功",
                content="路由关键词已保存",
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        else:
            InfoBar.error(
                title="保存失败",
                content="无法保存路由关键词",
                duration=2000,
                parent=self,
            )


class KeywordManagerWidget(QFrame):
    """关键词管理主界面 - V2.0 静态规则管理"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.current_shop_id = "default"  # 当前店铺ID
        self.setupUI()
        self.loadRulesFromRedis()

    def setupUI(self):
        """设置主界面UI"""
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(25)

        # 创建头部区域
        header_widget = self.createHeaderWidget()

        # 创建内容区域（表格）
        self.table_widget = KeywordTableWidget()
        self.reply_rules_panel = ReplyRulesPanel(self.current_shop_id)
        self.route_keywords_panel = RouteKeywordsPanel(self.current_shop_id)
        self.static_rules_tab = QWidget()
        static_layout = QVBoxLayout(self.static_rules_tab)
        static_layout.setContentsMargins(0, 0, 0, 0)
        static_layout.addWidget(self.table_widget)

        # 连接表格信号
        self.table_widget.edit_clicked.connect(self.onEditRule)
        self.table_widget.delete_clicked.connect(self.onDeleteRule)

        # 连接按钮信号
        self.add_btn.clicked.connect(self.onAddRule)
        self.import_btn.clicked.connect(self.onImportRules)

        self.pivot = SegmentedWidget(self)
        self.pivot.setFixedWidth(420)
        self.pivot.setStyleSheet("""
            SegmentedWidget {
                background-color: transparent;
            }
            SegmentedItem {
                color: #111827;
            }
            SegmentedItem:hover {
                color: #111827;
            }
        """)
        self.stacked_widget = QStackedWidget(self)
        self.stacked_widget.addWidget(self.static_rules_tab)
        self.stacked_widget.addWidget(self.reply_rules_panel)
        self.stacked_widget.addWidget(self.route_keywords_panel)
        self.pivot.addItem(routeKey="static_rules", text="静态回复", onClick=lambda: self._switchTab(0, "static_rules"))
        self.pivot.addItem(routeKey="reply_rules", text="一级话术", onClick=lambda: self._switchTab(1, "reply_rules"))
        self.pivot.addItem(routeKey="route_keywords", text="路由关键词", onClick=lambda: self._switchTab(2, "route_keywords"))
        self.pivot.setCurrentItem("static_rules")

        pivot_layout = QHBoxLayout()
        pivot_layout.addStretch()
        pivot_layout.addWidget(self.pivot)
        pivot_layout.addStretch()

        # 添加到主布局
        main_layout.addWidget(header_widget)
        main_layout.addLayout(pivot_layout)
        main_layout.addWidget(self.stacked_widget, 1)

        # 设置对象名
        self.setObjectName("静态规则管理")

    def _switchTab(self, index: int, route_key: str):
        self.stacked_widget.setCurrentIndex(index)
        self.pivot.setCurrentItem(route_key)

    def createHeaderWidget(self):
        """创建头部区域"""
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(20)

        # 标题
        title_label = SubtitleLabel("静态规则管理 (Level -1 拦截器)")

        # 统计信息
        self.stats_label = CaptionLabel("共 0 条规则")

        # 左侧标题区域
        title_area = QWidget()
        title_layout = QVBoxLayout(title_area)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(5)
        title_layout.addWidget(title_label)
        title_layout.addWidget(self.stats_label)

        # 添加规则按钮
        self.add_btn = PrimaryPushButton("添加规则")
        self.add_btn.setIcon(FIF.ADD)
        self.add_btn.setFixedSize(120, 40)

        # 批量导入按钮
        self.import_btn = PushButton("批量导入")
        self.import_btn.setIcon(FIF.FOLDER_ADD)
        self.import_btn.setFixedSize(120, 40)

        # 按钮容器
        buttons_widget = QWidget()
        buttons_layout = QHBoxLayout(buttons_widget)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)
        buttons_layout.addWidget(self.import_btn)
        buttons_layout.addWidget(self.add_btn)

        # 添加到头部布局
        header_layout.addWidget(title_area)
        header_layout.addStretch()
        header_layout.addWidget(buttons_widget)

        return header_widget

    def loadRulesFromRedis(self):
        """从 Redis 加载静态规则"""
        try:
            rules = redis_manager.get_static_rules(self.current_shop_id)
            self.refreshRuleList(rules)
        except Exception as e:
            logger.error(f"加载静态规则失败: {e}")
            InfoBar.error(
                title="加载失败",
                content=f"无法从 Redis 加载规则: {str(e)}",
                duration=3000,
                parent=self
            )

    def refreshRuleList(self, rules: dict):
        """刷新规则列表"""
        # 清空表格
        self.table_widget.clearTable()

        # 添加规则到表格
        for keyword, reply in rules.items():
            self.table_widget.addRule(keyword, reply)

        # 更新统计信息
        self.updateStats(len(rules))

    def updateStats(self, count: int):
        """更新统计信息"""
        self.stats_label.setText(f"共 {count} 条规则")

    def onAddRule(self):
        """添加规则"""
        dialog = RuleEditDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            keyword, reply = dialog.getValues()

            if not keyword or not reply:
                InfoBar.warning(
                    title="输入无效",
                    content="触发关键词和固定回复都不能为空",
                    duration=2000,
                    parent=self
                )
                return

            # 保存到 Redis
            if redis_manager.set_static_rule(self.current_shop_id, keyword, reply):
                InfoBar.success(
                    title="保存成功",
                    content=f"规则已同步至 Redis，立即生效",
                    duration=2000,
                    position=InfoBarPosition.TOP,
                    parent=self
                )
                # 刷新列表
                self.loadRulesFromRedis()
            else:
                InfoBar.error(
                    title="保存失败",
                    content="无法保存到 Redis",
                    duration=2000,
                    parent=self
                )

    def onEditRule(self, keyword: str, reply: str):
        """编辑规则"""
        dialog = RuleEditDialog(keyword=keyword, reply=reply, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_keyword, new_reply = dialog.getValues()

            if not new_keyword or not new_reply:
                InfoBar.warning(
                    title="输入无效",
                    content="触发关键词和固定回复都不能为空",
                    duration=2000,
                    parent=self
                )
                return

            # 如果关键词修改了，先删除旧规则
            if new_keyword != keyword:
                redis_manager.delete_static_rule(self.current_shop_id, keyword)

            # 保存新规则
            if redis_manager.set_static_rule(self.current_shop_id, new_keyword, new_reply):
                InfoBar.success(
                    title="更新成功",
                    content="规则已同步至 Redis，立即生效",
                    duration=2000,
                    position=InfoBarPosition.TOP,
                    parent=self
                )
                self.loadRulesFromRedis()
            else:
                InfoBar.error(
                    title="更新失败",
                    content="无法保存到 Redis",
                    duration=2000,
                    parent=self
                )

    def onDeleteRule(self, keyword: str):
        """删除规则"""
        reply = QMessageBox.question(
            self, '确认删除',
            f'确定要删除规则 "{keyword}" 吗？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            if redis_manager.delete_static_rule(self.current_shop_id, keyword):
                InfoBar.success(
                    title="删除成功",
                    content=f"规则 '{keyword}' 已删除",
                    duration=2000,
                    parent=self
                )
                self.loadRulesFromRedis()
            else:
                InfoBar.error(
                    title="删除失败",
                    content="无法从 Redis 删除规则",
                    duration=2000,
                    parent=self
                )

    def onImportRules(self):
        """批量导入规则"""
        # TODO: 实现批量导入对话框
        InfoBar.info(
            title="功能开发中",
            content="批量导入功能将在后续版本提供",
            duration=2000,
            parent=self
        )

    def reloadRules(self):
        """重新加载规则（供外部调用）"""
        self.loadRulesFromRedis()
