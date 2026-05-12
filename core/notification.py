"""
通知服务接口模块

定义前后端解耦的通知服务抽象基类。
用于跨线程安全的 UI 警报触发（如人工接管警报）。

包含：
- NotificationService: 抽象基类（接口定义）
- DummyNotificationService: 空壳实现（Headless 模式安全使用）
"""
from __future__ import annotations

from typing import Literal

from utils.logger_loguru import get_logger

logger = get_logger("NotificationService")


class NotificationService:
    """
    通知服务抽象基类

    用于前后端解耦，后端（LangGraph 异步线程）通过此接口触发 UI 警报，
    前端（PyQt6 主线程）实现具体的 UI 展示逻辑。

    设计原则：
    - 后端只调用抽象方法，不直接操作 UI
    - 前端通过 pyqtSignal 实现跨线程安全调用
    """

    def alert_human_fallback(
        self,
        shop_id: str,
        user_id: str,
        reason: str,
        alert_level: str = "low",
    ) -> None:
        """
        触发人工接管警报

        当 LangGraph 状态机判定需要转人工时调用此方法。
        UI 层实现应在右下角弹出警告卡片并播放提示音。

        Args:
            shop_id: 店铺 ID
            user_id: 用户 ID（from_uid）
            reason: 触发原因（如红线关键词命中）
            alert_level: 警报级别（"high" 高危 / "low" 低危）
        """
        raise NotImplementedError


class DummyNotificationService(NotificationService):
    """
    空壳通知服务（Headless 模式安全使用）

    用于 Linux/Docker 无头环境，绝对不加载任何 UI 相关依赖（如 PyQt6）。
    只记录日志，不执行任何 UI 操作。

    使用场景：
    - Docker 容器中后台运行（HEADLESS_MODE=1）
    - Linux 服务器无图形界面环境
    - CI/CD 自动化测试环境

    安全性保证：
    - 不导入 PyQt6 相关模块
    - 不触发任何 UI 渲染
    - 绝对不会因依赖缺失而崩溃
    """

    def alert_human_fallback(
        self,
        shop_id: str,
        user_id: str,
        reason: str,
        alert_level: str = "low",
    ) -> None:
        """
        拦截转人工请求并记录日志

        Headless 模式下，不执行任何 UI 操作。
        """
        logger.info(
            f"[Headless模式] 拦截到转人工请求: "
            f"shop_id={shop_id}, user_id={user_id}, reason={reason}, alert_level={alert_level}"
        )
