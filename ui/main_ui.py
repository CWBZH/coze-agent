import sys
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel
from PyQt6.QtGui import QFont, QIcon, QPixmap
from qfluentwidgets import FluentWindow,qrouter, NavigationItemPosition
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import SubtitleLabel, TeachingTip, TeachingTipTailPosition
from qfluentwidgets import Action
from utils.logger_loguru import get_logger
import time

class Widget(QFrame):

    def __init__(self, text: str, parent=None):
        super().__init__(parent=parent)
        # 创建标题标签
        self.label = SubtitleLabel(text, self)
        # 创建水平布局
        self.hBoxLayout = QHBoxLayout(self)
        # 设置标签文本居中对齐
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 将标签添加到布局中,设置居中对齐和拉伸因子1
        self.hBoxLayout.addWidget(self.label, 1, Qt.AlignmentFlag.AlignCenter)
        # 必须给子界面设置全局唯一的对象名
        self.setObjectName(text.replace(' ', '-'))

class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        t = time.perf_counter()
        self.setWindowTitle('拼多多AI客服助手')
        self.setWindowIcon(QIcon("icon/icon.ico"))
        self.logger = get_logger("MainWindow")
        self.logger.info(f"  基础属性初始化: {time.perf_counter()-t:.2f}s")

        # 延迟加载的视图
        self.knowledge_view = None
        self.monitor_view = None
        self.keyword_manager_view = None
        self.user_manager_view = None
        self.log_view = None
        self.settingInterface = None

        # 连接全局信号广播站（人工接管警报）
        from ui.signal_bus import global_signal_bus
        global_signal_bus.human_fallback_signal.connect(self._show_fallback_alert)
        self.logger.info("  已连接人工接管警报信号广播")

        t = time.perf_counter()
        # 立即初始化导航和窗口
        self.initWindow()
        self.logger.info(f"  initWindow: {time.perf_counter()-t:.2f}s")

        # 延迟加载各个视图，让窗口先显示
        QTimer.singleShot(200, self.lazy_load_views)

    def _show_fallback_alert(self, shop_id: str, user_id: str, reason: str, alert_level: str = "low") -> None:
        """
        显示人工接管警报（在主线程中安全执行）

        此槽函数由全局信号广播站触发，
        弹窗直接依附于主窗口（parent=self），解决父窗口丢失问题。

        警报分级处理：
        - high: 高危警报，播放声音，红色弹窗（10秒）
        - low: 低危警报，普通提示音，黄色弹窗（5秒）

        Args:
            shop_id: 店铺 ID
            user_id: 用户 ID
            reason: 触发原因
            alert_level: 警报级别（"high" 高危 / "low" 低危）
        """
        self.logger.info(
            f"[警报] 人工接管触发: shop_id={shop_id}, user_id={user_id}, "
            f"reason={reason}, alert_level={alert_level}"
        )

        # 所有转人工都播放提示音，高危使用更强提示。
        self._play_alert_sound_cross_platform(alert_level)

        # 高危警报：红色弹窗
        if alert_level == "high":
            self._show_high_alert_info_bar(shop_id, user_id, reason)
        # 低危警报：黄色弹窗
        else:
            self._show_low_alert_info_bar(shop_id, user_id, reason)

    def _play_alert_sound_cross_platform(self, alert_level: str = "low") -> None:
        """
        播放系统提示音（跨平台兼容）

        Windows: 使用 winsound
        Linux/Docker: 回退到 QApplication.beep，不崩溃
        """
        try:
            import winsound
            if alert_level == "high":
                winsound.MessageBeep(winsound.MB_ICONHAND)
            else:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            self.logger.debug(f"[警报] Windows 系统提示音已播放: level={alert_level}")
        except ImportError:
            try:
                QApplication.beep()
                self.logger.debug(f"[警报] Qt 提示音已播放: level={alert_level}")
            except Exception as e:
                self.logger.warning(f"[警报] Qt 提示音播放失败: {e}")
        except Exception as e:
            self.logger.warning(f"[警报] 播放警报音失败: {e}")

    def _show_high_alert_info_bar(self, shop_id: str, user_id: str, reason: str) -> None:
        """
        显示高危警报 InfoBar 弹窗

        红色错误级别，持续 10 秒，播放警报音。
        """
        try:
            from qfluentwidgets import InfoBar, InfoBarPosition
            from PyQt6.QtCore import Qt

            # 构建通知内容
            title = "⚠️ 高危警报 - 人工接管"
            content = f"店铺: {shop_id}\n用户: {user_id}\n原因: {reason}"

            # 显示 InfoBar，明确指定 parent=self
            InfoBar.error(
                title=title,
                content=content,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT,
                duration=10000,  # 10 秒后自动关闭
                parent=self,  # 关键：依附于主窗口
            )

            self.logger.info(f"[警报] 高危 InfoBar 已显示: {title}")

        except ImportError:
            self.logger.warning("[警报] qfluentwidgets 未安装，使用备用通知")
            self._show_fallback_alert_dialog(shop_id, user_id, reason)
        except Exception as e:
            self.logger.error(f"[警报] 显示高危 InfoBar 失败: {e}")
            self._show_fallback_alert_dialog(shop_id, user_id, reason)

    def _show_low_alert_info_bar(self, shop_id: str, user_id: str, reason: str) -> None:
        """
        显示低危警报 InfoBar 弹窗

        黄色警告级别，持续 5 秒，配合普通提示音。
        """
        try:
            from qfluentwidgets import InfoBar, InfoBarPosition
            from PyQt6.QtCore import Qt

            # 构建通知内容
            title = "📝 转人工提醒"
            content = f"店铺: {shop_id}\n用户: {user_id}\n原因: {reason}"

            # 显示 InfoBar，黄色警告级别
            InfoBar.warning(
                title=title,
                content=content,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.BOTTOM_RIGHT,
                duration=5000,  # 5 秒后自动关闭
                parent=self,  # 关键：依附于主窗口
            )

            self.logger.info(f"[警报] 低危 InfoBar 已显示: {title}")

        except ImportError:
            self.logger.warning("[警报] qfluentwidgets 未安装，使用备用通知")
        except Exception as e:
            self.logger.error(f"[警报] 显示低危 InfoBar 失败: {e}")

    def _show_fallback_alert_dialog(self, shop_id: str, user_id: str, reason: str) -> None:
        """
        备用通知方式（当 qfluentwidgets 不可用时）

        使用标准 QMessageBox。
        """
        try:
            from PyQt6.QtWidgets import QMessageBox
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("人工接管警报")
            msg.setText(f"店铺: {shop_id}\n用户: {user_id}\n原因: {reason}")
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.show()
        except Exception as e:
            self.logger.error(f"[警报] 备用对话框显示失败: {e}")

    def lazy_load_views(self):
        """延迟加载各个视图，提高启动速度"""
        t0 = time.perf_counter()
        # 局部按需导入，减少启动时的重依赖加载
        t = time.perf_counter()
        from ui.auto_reply_ui import AutoReplyUI
        self.logger.info(f"  import AutoReplyUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        from ui.keyword_ui import KeywordManagerWidget
        self.logger.info(f"  import KeywordManagerWidget: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        from ui.user_ui import UserManagerWidget
        self.logger.info(f"  import UserManagerWidget: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        from ui.log_ui import LogUI
        self.logger.info(f"  import LogUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        from ui.setting_ui import SettingUI
        self.logger.info(f"  import SettingUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        from ui.Knowledge_ui import KnowledgeUI
        self.logger.info(f"  import KnowledgeUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.monitor_view = AutoReplyUI(self)
        self.logger.info(f"  AutoReplyUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.keyword_manager_view = KeywordManagerWidget(self)
        self.logger.info(f"  KeywordManagerWidget: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.user_manager_view = UserManagerWidget(self)
        self.logger.info(f"  UserManagerWidget: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.log_view = LogUI(self)
        self.logger.info(f"  LogUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.knowledge_view = KnowledgeUI(self)
        self.logger.info(f"  KnowledgeUI: {time.perf_counter()-t:.2f}s")
        t = time.perf_counter()
        self.settingInterface = SettingUI(self)
        self.logger.info(f"  SettingUI: {time.perf_counter()-t:.2f}s")

        # 初始化导航
        self.initNavigation()
        self.logger.info(f"延迟视图初始化耗时: {time.perf_counter() - t0:.2f}s")

    # 初始化导航栏
    def initNavigation(self):
        self.navigationInterface.setExpandWidth(200)
        self.navigationInterface.setMinimumWidth(200)
        self.addSubInterface(self.monitor_view, FIF.CHAT, '自动回复')
        self.addSubInterface(self.keyword_manager_view, FIF.EDIT, '关键词管理')
        self.addSubInterface(self.user_manager_view, FIF.PEOPLE, '账号管理')
        self.addSubInterface(self.knowledge_view, FIF.DOCUMENT, '知识库')
        self.addSubInterface(self.log_view, FIF.HISTORY, '日志管理', NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.settingInterface, FIF.SETTING, '设置', NavigationItemPosition.BOTTOM)


    # 初始化窗口
    def initWindow(self):
        # 先设置最小尺寸
        self.setMinimumWidth(1280)
        self.setMinimumHeight(720)
        
        # 设置默认尺寸（避免几何冲突）
        self.resize(1400, 800)
        
        # 最后最大化显示
        self.showMaximized()


    def showQRCode(self):
        """显示二维码TeachingTip"""
        try:
            tip = TeachingTip.create(
                target=self.navigationInterface,
                image="icon/Customer-Agent-qr.png",
                icon=FIF.PEOPLE,
                title="联系我们",
                content="扫码关注获取更多信息和支持",
                isClosable=True,
                duration=-1,
                tailPosition=TeachingTipTailPosition.LEFT,
                parent=self
            )
            
            # 显示TeachingTip
            tip.show()
            
        except Exception as e:
            self.logger.error(f"显示二维码失败: {e}")

    def closeEvent(self, a0):
        """ 重写窗口关闭事件，确保后台线程安全退出 """

        # 停止所有自动回复线程
        try:
            from ui.auto_reply_ui import auto_reply_manager
            auto_reply_manager.stop_all()
        except Exception:
            pass

        super().closeEvent(a0) 
