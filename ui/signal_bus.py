"""
全局信号广播站

用于前后端完全解耦的跨线程信号传递。
解决父窗口丢失问题：所有信号在主窗口中连接，弹窗直接依附于主窗口。

V2.0 Playwright 集成：
- 新增 Playwright 消息信号，用于隔离舱向主线程发送新消息
- 新增 Playwright 状态信号，用于报告连接状态变化
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class SignalBus(QObject):
    """
    全局信号广播站

    作为后端（LangGraph 异步线程）和前端（PyQt 主窗口）之间的通信桥梁。
    所有 UI 相关的信号在此定义，由主窗口统一接收和处理。

    设计原则：
    - 后端只发射信号，不直接操作 UI
    - 前端（主窗口）统一接收信号并处理 UI 操作
    - 弹窗直接依附于主窗口（parent=self），解决父窗口丢失问题
    """

    # =========================================================================
    # 人工接管警报信号
    # =========================================================================
    # 参数: (shop_id, user_id, reason, alert_level)
    # alert_level: "high" 高危 / "low" 低危
    human_fallback_signal = pyqtSignal(str, str, str, str)

    # =========================================================================
    # AI 思考链路信号
    # =========================================================================
    # 参数: (session_id, intent, latency, knowledge_source, response_preview)
    ai_thought_chain_signal = pyqtSignal(str, str, float, str, str)

    # =========================================================================
    # Playwright 隔离舱信号
    # =========================================================================
    # 新消息进线信号：参数 (shop_id, user_id, raw_query)
    # 当 Playwright 监听到新消息时发射，通知主线程处理
    playwright_new_message_signal = pyqtSignal(str, str, str)

    # 状态变化信号：参数 (status_code, message)
    # status_code: 0=断开, 1=连接中, 2=已连接, 3=错误
    playwright_status_signal = pyqtSignal(int, str)

    # 回复发送结果信号：参数 (shop_id, user_id, success, error_msg)
    playwright_reply_result_signal = pyqtSignal(str, str, bool, str)


# 全局单例广播站
global_signal_bus = SignalBus()