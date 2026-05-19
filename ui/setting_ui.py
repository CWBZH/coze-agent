# 设置界面 - V2.0 架构重构版
#
# 架构改进：
# - UI 层与配置存储完全解耦
# - 所有配置操作通过 ConfigManager 进行
# - 移除所有 os.getenv、dotenv、Redis 直接调用
# - UI 仅负责数据收集和展示

from PyQt6.QtCore import Qt, pyqtSignal, QTime
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QVBoxLayout, QWidget, QLabel,
                            QFormLayout, QMessageBox)
from PyQt6.QtGui import QFont
from qfluentwidgets import (CardWidget, SubtitleLabel, CaptionLabel, BodyLabel,
                           PrimaryPushButton, PushButton, StrongBodyLabel,
                           LineEdit, ScrollArea, FluentIcon as FIF,
                           InfoBar, InfoBarPosition, TextEdit, PasswordLineEdit,
                           TimePicker)

from core.config_manager import config_manager
from ui.theme import TEXT_MUTED
from utils.logger_loguru import get_logger

logger = get_logger("SettingUI")


class LLMConfigCard(CardWidget):
    """LLM配置卡片 - 仅负责数据收集和展示"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()

    def setupUI(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # 卡片标题
        title_label = StrongBodyLabel("LLM模型配置")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)

        # 表单布局
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft)

        # API Base URL
        self.api_base_edit = LineEdit()
        self.api_base_edit.setPlaceholderText("https://ark.cn-beijing.volces.com/api/v3")
        form_layout.addRow("API Base URL:", self.api_base_edit)

        # API Key
        self.api_key_edit = PasswordLineEdit()
        self.api_key_edit.setPlaceholderText("输入您的 API Key")
        form_layout.addRow("API Key:", self.api_key_edit)

        # Model Name
        self.model_name_edit = LineEdit()
        self.model_name_edit.setPlaceholderText("输入模型名称，如：doubao-seed-1-6-flash-250828")
        form_layout.addRow("模型名称:", self.model_name_edit)

        layout.addLayout(form_layout)

        # 说明文本
        description_label = CaptionLabel(
            "配置LLM模型的连接参数。\n"
            "支持OpenAI兼容的API接口，包括豆包、通义千问等模型。"
        )
        description_label.setStyleSheet(f"color: {TEXT_MUTED}; padding: 8px 0; font-weight: 500;")
        layout.addWidget(description_label)

    def getConfig(self) -> dict:
        """获取配置（仅收集界面数据）"""
        return {
            "api_base": self.api_base_edit.text().strip(),
            "api_key": self.api_key_edit.text().strip(),
            "model_name": self.model_name_edit.text().strip()
        }

    def setConfig(self, config: dict):
        """设置配置（仅更新界面显示）"""
        self.api_base_edit.setText(config.get("api_base", ""))
        self.api_key_edit.setText(config.get("api_key", ""))
        self.model_name_edit.setText(config.get("model_name", ""))


class PromptConfigCard(CardWidget):
    """提示词配置卡片 - 仅负责数据收集和展示"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()

    def setupUI(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # 卡片标题
        title_label = StrongBodyLabel("AI提示词配置")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)

        # 表单布局
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft)

        # 行为指令（用户唯一可配置的字段）
        self.instructions_edit = TextEdit()
        self.instructions_edit.setPlaceholderText("输入行为指令，每行一条")
        self.instructions_edit.setMaximumHeight(200)
        form_layout.addRow("行为指令:", self.instructions_edit)

        layout.addLayout(form_layout)

        # 说明文本
        description_label = CaptionLabel(
            "配置AI助手的行为指令。\n"
            "角色描述和工具说明由系统自动管理，无需手动配置。"
        )
        description_label.setStyleSheet(f"color: {TEXT_MUTED}; padding: 8px 0; font-weight: 500;")
        layout.addWidget(description_label)

    def getConfig(self) -> dict:
        """获取配置（仅收集界面数据）"""
        return {
            "instructions": [
                line.strip() for line in self.instructions_edit.toPlainText().splitlines() if line.strip()
            ]
        }

    def setConfig(self, config: dict):
        """设置配置（仅更新界面显示）"""
        instructions = config.get("instructions", [])
        if isinstance(instructions, list):
            self.instructions_edit.setPlainText("\n".join(instructions))
        elif isinstance(instructions, str):
            self.instructions_edit.setPlainText(instructions)


class ReplyRulesConfigCard(CardWidget):
    """一级拦截和确定性模板话术配置卡片。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()

    def setupUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        title_label = StrongBodyLabel("一级拦截与固定话术配置")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)

        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft)

        self.general_reply_edit = LineEdit()
        self.unknown_reply_edit = LineEdit()
        self.logistics_reply_edit = LineEdit()
        self.no_product_match_reply_edit = LineEdit()
        self.child_known_age_reply_template_edit = LineEdit()
        self.child_unknown_age_reply_edit = LineEdit()

        form_layout.addRow("通用默认回复:", self.general_reply_edit)
        form_layout.addRow("意图不明确回复:", self.unknown_reply_edit)
        form_layout.addRow("物流默认回复:", self.logistics_reply_edit)
        form_layout.addRow("无商品匹配回复:", self.no_product_match_reply_edit)
        form_layout.addRow("年龄明确模板:", self.child_known_age_reply_template_edit)
        form_layout.addRow("年龄未知回复:", self.child_unknown_age_reply_edit)

        self.short_default_phrases_edit = TextEdit()
        self.short_default_phrases_edit.setPlaceholderText("每行一个短句，例如：好吧、嗯、在吗")
        self.short_default_phrases_edit.setMaximumHeight(120)
        form_layout.addRow("短句默认回复词:", self.short_default_phrases_edit)

        self.child_age_terms_edit = TextEdit()
        self.child_age_terms_edit.setPlaceholderText("每行一个触发词，例如：岁、宝宝、孕妇、能用")
        self.child_age_terms_edit.setMaximumHeight(90)
        form_layout.addRow("年龄/人群触发词:", self.child_age_terms_edit)

        layout.addLayout(form_layout)

        description_label = CaptionLabel(
            "这些配置会作用于一级拦截层和确定性模板回复，保存后重启或重新初始化 Agent 生效。"
        )
        description_label.setStyleSheet(f"color: {TEXT_MUTED}; padding: 8px 0; font-weight: 500;")
        layout.addWidget(description_label)

    def getConfig(self) -> dict:
        return {
            "general_reply": self.general_reply_edit.text().strip(),
            "unknown_reply": self.unknown_reply_edit.text().strip(),
            "logistics_reply": self.logistics_reply_edit.text().strip(),
            "no_product_match_reply": self.no_product_match_reply_edit.text().strip(),
            "child_known_age_reply_template": self.child_known_age_reply_template_edit.text().strip(),
            "child_unknown_age_reply": self.child_unknown_age_reply_edit.text().strip(),
            "short_default_phrases": self._read_lines(self.short_default_phrases_edit),
            "child_age_terms": self._read_lines(self.child_age_terms_edit),
        }

    def setConfig(self, config: dict):
        config = config or {}
        self.general_reply_edit.setText(config.get("general_reply", ""))
        self.unknown_reply_edit.setText(config.get("unknown_reply", ""))
        self.logistics_reply_edit.setText(config.get("logistics_reply", ""))
        self.no_product_match_reply_edit.setText(config.get("no_product_match_reply", ""))
        self.child_known_age_reply_template_edit.setText(config.get("child_known_age_reply_template", ""))
        self.child_unknown_age_reply_edit.setText(config.get("child_unknown_age_reply", ""))
        self.short_default_phrases_edit.setPlainText("\n".join(config.get("short_default_phrases", [])))
        self.child_age_terms_edit.setPlainText("\n".join(config.get("child_age_terms", [])))

    def _read_lines(self, edit: TextEdit) -> list:
        return [line.strip() for line in edit.toPlainText().splitlines() if line.strip()]


class BusinessHoursCard(CardWidget):
    """业务时间配置卡片 - 仅负责数据收集和展示"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()

    def setupUI(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # 卡片标题
        title_label = StrongBodyLabel("业务时间设置")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)

        # 表单布局
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft)

        # 开始时间
        self.start_time_picker = TimePicker()
        self.start_time_picker.setTime(QTime(8, 0))
        form_layout.addRow("开始时间:", self.start_time_picker)

        # 结束时间
        self.end_time_picker = TimePicker()
        self.end_time_picker.setTime(QTime(23, 0))
        form_layout.addRow("结束时间:", self.end_time_picker)

        layout.addLayout(form_layout)

        # 说明文本
        description_label = CaptionLabel(
            "设置AI客服的工作时间。在工作时间内，系统将自动响应客户消息。\n"
            "在非工作时间，系统将不会自动回复。"
        )
        description_label.setStyleSheet(f"color: {TEXT_MUTED}; padding: 8px 0; font-weight: 500;")
        layout.addWidget(description_label)

    def getConfig(self) -> dict:
        """获取配置（仅收集界面数据）"""
        return {
            "start": self.start_time_picker.getTime().toString("HH:mm"),
            "end": self.end_time_picker.getTime().toString("HH:mm")
        }

    def setConfig(self, config: dict):
        """设置配置（仅更新界面显示）"""
        # 解析开始时间
        start_time_str = config.get("start", "08:00")
        start_time = QTime.fromString(start_time_str, "HH:mm")
        if start_time.isValid():
            self.start_time_picker.setTime(start_time)

        # 解析结束时间
        end_time_str = config.get("end", "23:00")
        end_time = QTime.fromString(end_time_str, "HH:mm")
        if end_time.isValid():
            self.end_time_picker.setTime(end_time)


class SettingUI(QFrame):
    """设置界面 - UI 层与配置存储完全解耦"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.logger = logger
        self.current_shop_id = "default"  # 当前店铺ID

        self.setupUI()
        self.loadConfig()

        self.setObjectName("设置")

    def setupUI(self):
        """设置主界面UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(25)

        # 创建头部区域
        header_widget = self.createHeaderWidget()

        # 创建内容区域
        content_widget = self.createContentWidget()

        # 连接按钮信号
        self.save_btn.clicked.connect(self.onSaveConfig)
        self.reset_btn.clicked.connect(self.onResetConfig)

        # 添加到主布局
        main_layout.addWidget(header_widget)
        main_layout.addWidget(content_widget, 1)

    def createHeaderWidget(self):
        """创建头部区域"""
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(20)

        # 标题
        title_label = SubtitleLabel("系统设置")
        title_label.setFont(QFont("Microsoft YaHei", 18, QFont.Weight.Bold))

        # 描述
        description_label = CaptionLabel("配置AI客服的基本参数和工作时间")
        description_label.setStyleSheet(f"color: {TEXT_MUTED}; font-weight: 500;")

        # 左侧标题区域
        title_area = QWidget()
        title_layout = QVBoxLayout(title_area)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(5)
        title_layout.addWidget(title_label)
        title_layout.addWidget(description_label)

        # 按钮区域
        buttons_widget = QWidget()
        buttons_layout = QHBoxLayout(buttons_widget)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)

        # 重置按钮
        self.reset_btn = PushButton("重置")
        self.reset_btn.setIcon(FIF.UPDATE)
        self.reset_btn.setFixedSize(80, 40)

        # 保存按钮
        self.save_btn = PrimaryPushButton("保存")
        self.save_btn.setIcon(FIF.SAVE)
        self.save_btn.setFixedSize(100, 40)

        buttons_layout.addWidget(self.reset_btn)
        buttons_layout.addWidget(self.save_btn)

        # 添加到头部布局
        header_layout.addWidget(title_area)
        header_layout.addStretch()
        header_layout.addWidget(buttons_widget)

        return header_widget

    def createContentWidget(self):
        """创建内容区域"""
        scroll_area = ScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        scroll_area.setStyleSheet("""
            ScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setSpacing(20)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 创建配置卡片
        self.llm_config_card = LLMConfigCard()
        self.prompt_config_card = PromptConfigCard()
        self.business_hours_card = BusinessHoursCard()

        # 添加到布局
        content_layout.addWidget(self.llm_config_card)
        content_layout.addWidget(self.prompt_config_card)
        content_layout.addWidget(self.business_hours_card)
        content_layout.addStretch()

        content_container.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border: none;
            }
        """)

        scroll_area.setWidget(content_container)

        return scroll_area

    def loadConfig(self):
        """加载配置 - 通过 ConfigManager"""
        try:
            # 从 ConfigManager 获取配置
            all_config = config_manager.get_all_config(self.current_shop_id)

            # 设置到界面（仅更新显示，不涉及底层存储）
            self.llm_config_card.setConfig(all_config["llm"])
            self.prompt_config_card.setConfig(all_config["prompt"])
            self.business_hours_card.setConfig(all_config["business_hours"])

            self.logger.info("配置加载成功")

        except Exception as e:
            self.logger.error(f"加载配置失败: {e}")
            QMessageBox.warning(self, "加载失败", f"加载配置失败：{str(e)}")

    def collectConfigData(self) -> dict:
        """收集界面上的所有配置数据（纯 UI 操作）"""
        return {
            "llm": self.llm_config_card.getConfig(),
            "prompt": self.prompt_config_card.getConfig(),
            "business_hours": self.business_hours_card.getConfig(),
            "shop_id": self.current_shop_id,
        }

    def onSaveConfig(self):
        """保存配置 - 通过 ConfigManager"""
        try:
            # 1. 收集界面数据
            config_data = self.collectConfigData()

            # 2. 验证必填项
            llm_config = config_data["llm"]
            if not llm_config.get("api_key"):
                QMessageBox.warning(self, "配置错误", "请输入LLM API Key！")
                return
            if not llm_config.get("model_name"):
                QMessageBox.warning(self, "配置错误", "请输入LLM模型名称！")
                return

            # 3. 验证时间设置
            start_time = self.business_hours_card.start_time_picker.getTime()
            end_time = self.business_hours_card.end_time_picker.getTime()

            if start_time >= end_time:
                QMessageBox.warning(self, "时间设置错误", "开始时间必须早于结束时间！")
                return

            # 4. 通过 ConfigManager 保存配置
            success = config_manager.update_config(config_data)

            if success:
                self.logger.info("配置保存成功")

                InfoBar.success(
                    title="保存成功",
                    content="配置已保存！",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                    parent=self
                )
            else:
                QMessageBox.critical(self, "保存失败", "配置保存失败，请检查日志")

        except Exception as e:
            self.logger.error(f"保存配置失败: {e}")
            QMessageBox.critical(self, "保存失败", f"保存配置时发生错误：{str(e)}")

    def onResetConfig(self):
        """重置配置 - 重新从 ConfigManager 加载"""
        reply = QMessageBox.question(
            self,
            "确认重置",
            "确定要重置所有配置吗？\n这将重新加载配置文件中的原始设置。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                # 重新加载配置
                self.loadConfig()
                self.logger.info("配置已重置")

                InfoBar.success(
                    title="重置成功",
                    content="配置已重置为配置文件中的设置！",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                    parent=self
                )
            except Exception as e:
                self.logger.error(f"重置配置失败: {e}")
                QMessageBox.critical(self, "重置失败", f"重置配置失败：{str(e)}")
