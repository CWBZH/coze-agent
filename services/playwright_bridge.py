"""
Playwright 桥接控制器模块
========================

实现主线程与 Playwright 隔离舱的桥接，完成消息调度全链路闭环。

核心职责：
1. 连接 SignalBus 的 playwright_new_message_signal
2. 接收新消息后调用 CustomerAgent 进行意图路由和回复生成
3. 将生成的回复通过 PlaywrightServiceManager 发送

架构设计：
- 主线程（PyQt 事件循环）接收信号
- 调用 CustomerAgent（可能涉及异步操作）
- 将结果发送到 Playwright 隔离舱

V2.0 Playwright 集成 SDD 实现
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from ui.signal_bus import global_signal_bus
from services.pdd_protocol_service import pdd_protocol_service_manager
from utils.logger_loguru import get_logger

if TYPE_CHECKING:
    from Agent.CustomerAgent.custom.customer_agent import CustomerAgent

logger = get_logger("PlaywrightBridge")


class PlaywrightBridge(QObject):
    """
    Playwright 桥接控制器

    作为主线程与 Playwright 隔离舱之间的桥梁，完成消息调度全链路。

    使用示例：
        bridge = PlaywrightBridge()

        # 连接信号
        bridge.reply_generated.connect(bridge._send_reply_to_playwright)

        # 启动桥接
        bridge.start()

        # 停止桥接
        bridge.stop()
    """

    # 内部信号：回复生成完成
    reply_generated = pyqtSignal(str, str, str)  # shop_id, user_id, reply_text

    def __init__(self, customer_agent: Optional["CustomerAgent"] = None, parent=None):
        super().__init__(parent)
        self.customer_agent = customer_agent
        self._connected = False

        logger.info("PlaywrightBridge 初始化完成")

    def set_customer_agent(self, agent: "CustomerAgent"):
        """设置 CustomerAgent 实例"""
        self.customer_agent = agent

    def start(self):
        """启动桥接，连接信号"""
        if self._connected:
            logger.warning("PlaywrightBridge 已启动")
            return

        # 连接 Playwright 新消息信号
        global_signal_bus.playwright_new_message_signal.connect(
            self._on_new_message_received
        )

        # 连接回复生成信号
        self.reply_generated.connect(self._send_reply_to_playwright)

        self._connected = True
        logger.info("PlaywrightBridge 已启动，信号已连接")

    def stop(self):
        """停止桥接，断开信号"""
        if not self._connected:
            return

        try:
            global_signal_bus.playwright_new_message_signal.disconnect(
                self._on_new_message_received
            )
            self.reply_generated.disconnect(self._send_reply_to_playwright)
        except TypeError:
            # 信号可能已断开
            pass

        self._connected = False
        logger.info("PlaywrightBridge 已停止")

    def _on_new_message_received(self, shop_id: str, user_id: str, raw_query: str):
        """
        新消息接收槽函数

        ⚠️ 此方法在主线程（PyQt 事件循环）中执行

        核心流程：
        1. 接收 Playwright 隔离舱发来的新消息
        2. 调用 CustomerAgent 进行意图路由和回复生成
        3. 将生成的回复发送到 Playwright 隔离舱

        Args:
            shop_id: 店铺ID
            user_id: 用户ID
            raw_query: 原始消息内容
        """
        logger.info(f"收到新消息: shop_id={shop_id}, user_id={user_id}, query={raw_query[:50]}")

        try:
            # 1. 检查 CustomerAgent 是否可用
            if not self.customer_agent:
                logger.warning("CustomerAgent 未设置，无法处理消息")
                return

            # 2. 构建 Context 对象
            from bridge.context import Context

            context = Context(
                kwargs={
                    "shop_id": shop_id,
                    "user_id": user_id,
                }
            )

            # 3. 调用 CustomerAgent 进行回复生成
            # ⚠️ CustomerAgent.async_reply 是异步方法，需要在事件循环中执行
            reply = self._call_agent_sync(raw_query, context)

            if reply:
                # 4. 提取回复文本
                reply_text = reply.content if hasattr(reply, 'content') else str(reply)

                logger.info(f"回复生成完成: user_id={user_id}, reply={reply_text[:50]}")

                # 5. 发射回复生成信号（发送到 Playwright 隔离舱）
                self.reply_generated.emit(shop_id, user_id, reply_text)

            else:
                logger.warning(f"回复生成失败: user_id={user_id}")

        except Exception as e:
            logger.exception(f"处理新消息异常: {e}")

    def _call_agent_sync(self, query: str, context) -> Optional["Reply"]:
        """
        同步调用 CustomerAgent

        由于 CustomerAgent.async_reply 是异步方法，我们需要在事件循环中执行。

        Args:
            query: 用户查询
            context: 上下文对象

        Returns:
            Reply 对象或 None
        """
        try:
            # 尝试获取当前事件循环
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 如果循环正在运行，使用 run_coroutine_threadsafe
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run,
                            self.customer_agent.async_reply(query, context)
                        )
                        return future.result(timeout=30)
                else:
                    # 循环未运行，直接运行
                    return loop.run_until_complete(
                        self.customer_agent.async_reply(query, context)
                    )
            except RuntimeError:
                # 没有事件循环，创建新的
                return asyncio.run(self.customer_agent.async_reply(query, context))

        except Exception as e:
            logger.exception(f"调用 CustomerAgent 失败: {e}")
            return None

    def _send_reply_to_playwright(self, shop_id: str, user_id: str, reply_text: str):
        """
        发送回复到 Playwright 隔离舱

        Args:
            shop_id: 店铺ID
            user_id: 用户ID
            reply_text: 回复内容
        """
        try:
            success = pdd_protocol_service_manager.send_reply(shop_id, user_id, reply_text)

            if success:
                logger.debug(f"回复已发送到 Playwright 队列: user_id={user_id}")
            else:
                logger.warning(f"发送回复到 Playwright 失败: user_id={user_id}")

        except Exception as e:
            logger.exception(f"发送回复异常: {e}")


# =============================================================================
# 便捷函数
# =============================================================================

def create_playwright_bridge(customer_agent: "CustomerAgent" = None) -> PlaywrightBridge:
    """
    创建并启动 Playwright 桥接控制器

    Args:
        customer_agent: CustomerAgent 实例

    Returns:
        已启动的 PlaywrightBridge 实例
    """
    bridge = PlaywrightBridge(customer_agent)
    bridge.start()
    return bridge


__all__ = ["PlaywrightBridge", "create_playwright_bridge"]