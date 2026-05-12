"""
UI 通知服务实现

基于 PyQt6 的跨线程安全通知服务。
通过全局信号广播站实现前后端完全解耦。

V2.0 改进：
- 防抖机制迁移至 Redis（解决慢性内存泄漏）
- 本地字典 _last_alert_times 已移除
- 支持警报分级（高危/低危）

V2.0 战役七：上线预备重构
- 抽离硬编码 TTL 到 core.config
"""
from __future__ import annotations

from PyQt6.QtCore import QObject

from core.notification import NotificationService
from database.redis_manager import redis_manager
from ui.signal_bus import global_signal_bus
from utils.logger_loguru import get_logger

# 导入集中式配置
from core.config import ALERT_COOLDOWN_TTL

logger = get_logger("UINotificationService")


class UINotificationService(QObject, NotificationService):
    """
    PyQt UI 通知服务实现

    多重继承 QObject 和 NotificationService：
    - QObject: 提供对象管理能力
    - NotificationService: 定义抽象接口

    跨线程安全原理：
    - 后端在异步线程中调用 alert_human_fallback()
    - 该方法通过全局广播站发射信号
    - PyQt 自动将信号投递到主线程
    - 主窗口中连接的槽函数处理 UI 操作

    防抖机制（Redis 实现）：
    - 解决慢性内存泄漏问题
    - 本地字典在长期运行中会无限增长
    - Redis TTL 自动过期确保内存可控

    警报分级：
    - high: 高危警报（红线关键词），强提示音，红色弹窗
    - low: 低危警报（图片、普通请求），普通提示音，黄色弹窗
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        logger.info("UINotificationService 初始化完成（Redis 防抖模式 + 警报分级）")

    def alert_human_fallback(
        self,
        shop_id: str,
        user_id: str,
        reason: str,
        alert_level: str = "low",
    ) -> None:
        """
        触发人工接管警报（跨线程安全 + Redis 防抖 + 警报分级）

        此方法在 LangGraph 异步线程中被调用。
        通过全局广播站发射信号，由主窗口接收并处理。

        Args:
            shop_id: 店铺 ID
            user_id: 用户 ID
            reason: 触发原因
            alert_level: 警报级别（"high" 高危 / "low" 低危）
        """
        # Redis 防抖检查（解决慢性内存泄漏）
        # 本地字典 _last_alert_times 已移除
        cooldown_key = f"{user_id}:{alert_level}:{reason}"
        if not redis_manager.set_alert_cooldown(cooldown_key, ttl=ALERT_COOLDOWN_TTL):
            logger.info(
                f"[Redis防抖] 用户 {user_id} 同类警报冷却中，跳过广播: "
                f"alert_level={alert_level}, reason={reason}"
            )
            return

        # 通过全局广播站发射信号（包含警报级别）
        logger.info(
            f"[广播] 发射人工接管信号: shop_id={shop_id}, user_id={user_id}, "
            f"alert_level={alert_level}, reason={reason}"
        )
        global_signal_bus.human_fallback_signal.emit(shop_id, user_id, reason, alert_level)
