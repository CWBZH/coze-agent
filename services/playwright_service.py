"""
Playwright 网页自动化服务模块
============================

实现 Playwright 与 PyQt 的安全集成，彻底解决双事件循环冲突。

核心设计：
- PlaywrightWorkerThread: QThread 隔离舱，内部运行独立的 asyncio 事件循环
- 指令队列: queue.Queue 实现主线程到隔离舱的安全通信
- 信号桥接: 通过 SignalBus 向主线程发送新消息和状态变化

架构原则：
- 所有 Playwright 代码必须跑在隔离舱的独立事件循环中
- 主线程通过队列下发指令，不直接调用 Playwright API
- 隔离舱通过信号向主线程报告状态和消息，不直接操作 UI

V2.0 Playwright 集成 SDD 实现
"""
from __future__ import annotations

import asyncio
import queue
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable

from PyQt6.QtCore import QThread, pyqtSignal

from ui.signal_bus import global_signal_bus
from utils.logger_loguru import get_logger

logger = get_logger("PlaywrightService")


# =============================================================================
# 状态码定义
# =============================================================================

class PlaywrightStatus(Enum):
    """Playwright 状态码"""
    DISCONNECTED = 0      # 断开
    CONNECTING = 1        # 连接中
    CONNECTED = 2         # 已连接
    ERROR = 3             # 错误


# =============================================================================
# 指令数据结构
# =============================================================================

@dataclass
class ReplyCommand:
    """回复指令"""
    shop_id: str
    user_id: str
    reply_text: str
    timestamp: float


@dataclass
class StopCommand:
    """停止指令"""
    reason: str = "user_request"


# =============================================================================
# Playwright 隔离舱线程
# =============================================================================

class PlaywrightWorkerThread(QThread):
    """
    Playwright 工作线程隔离舱

    核心设计：
    1. run() 方法内创建独立的 asyncio.new_event_loop()
    2. 所有 Playwright 代码跑在这个独立循环中
    3. 通过 queue.Queue 接收主线程下发的指令
    4. 通过 SignalBus 向主线程发送新消息和状态变化

    使用示例：
        worker = PlaywrightWorkerThread(
            shop_id="12345",
            pdd_url="https://mms.pinduoduo.com/..."
        )

        # 连接信号
        global_signal_bus.playwright_new_message_signal.connect(self.on_new_message)
        global_signal_bus.playwright_status_signal.connect(self.on_status_change)

        # 启动线程
        worker.start()

        # 发送回复指令
        worker.send_reply("12345", "user1", "您好，请问有什么可以帮助您？")

        # 停止线程
        worker.stop()
    """

    # 内部信号（用于跨线程安全通信）
    _internal_stop_signal = pyqtSignal()

    def __init__(
        self,
        shop_id: str,
        pdd_url: str,
        cookies: Optional[dict] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.shop_id = shop_id
        self.pdd_url = pdd_url
        self.cookies = cookies or {}

        # 指令队列（主线程写入，隔离舱读取）
        self._command_queue: queue.Queue = queue.Queue()

        # 运行状态标志
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Playwright 对象（仅在隔离舱内部使用）
        self._browser = None
        self._page = None
        self._playwright = None

        logger.info(f"PlaywrightWorkerThread 初始化: shop_id={shop_id}")

    # =========================================================================
    # 主线程调用接口（安全写入队列）
    # =========================================================================

    def send_reply(self, shop_id: str, user_id: str, reply_text: str):
        """
        发送回复指令（主线程调用）

        Args:
            shop_id: 店铺ID
            user_id: 用户ID
            reply_text: 回复内容
        """
        command = ReplyCommand(
            shop_id=shop_id,
            user_id=user_id,
            reply_text=reply_text,
            timestamp=asyncio.get_event_loop().time() if asyncio.get_event_loop() else 0,
        )
        self._command_queue.put(command)
        logger.debug(f"回复指令已入队: user_id={user_id}")

    def stop(self):
        """停止线程（主线程调用）"""
        self._command_queue.put(StopCommand())
        self._running = False
        logger.info("停止指令已入队")

    # =========================================================================
    # 隔离舱核心逻辑（独立事件循环）
    # =========================================================================

    def run(self):
        """
        线程主入口 - 创建独立事件循环并运行 Playwright

        ⚠️ 关键设计：
        - 必须调用 asyncio.new_event_loop() 创建新循环
        - 所有 Playwright async API 必须跑在这个循环中
        - 通过 loop.run_until_complete() 或 loop.create_task() 执行异步任务
        """
        # 1. 创建并设置独立的事件循环
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self._running = True

        logger.info("Playwright 隔离舱事件循环已创建")

        try:
            # 2. 启动 Playwright 并连接到拼多多商家后台
            self._loop.run_until_complete(self._init_playwright())

            # 3. 报告连接成功状态
            global_signal_bus.playwright_status_signal.emit(
                PlaywrightStatus.CONNECTED.value,
                "已连接到拼多多商家后台"
            )

            # 4. 创建两个并发任务：消息监听 + 指令消费
            listen_task = self._loop.create_task(self._listen_for_messages())
            consume_task = self._loop.create_task(self._consume_commands())

            # 5. 等待任务完成（或收到停止指令）
            self._loop.run_until_complete(
                asyncio.gather(listen_task, consume_task, return_exceptions=True)
            )

        except Exception as e:
            logger.exception(f"Playwright 隔离舱运行异常: {e}")
            global_signal_bus.playwright_status_signal.emit(
                PlaywrightStatus.ERROR.value,
                str(e)
            )

        finally:
            # 6. 清理资源
            self._cleanup()
            self._loop.close()
            logger.info("Playwright 隔离舱事件循环已关闭")

    async def _init_playwright(self):
        """
        初始化 Playwright 浏览器和页面

        ⚠️ 必须在隔离舱的独立事件循环中调用
        """
        from playwright.async_api import async_playwright

        logger.info("正在启动 Playwright...")

        # 报告连接中状态
        global_signal_bus.playwright_status_signal.emit(
            PlaywrightStatus.CONNECTING.value,
            "正在连接..."
        )

        # 启动 Playwright
        self._playwright = await async_playwright().start()

        # 启动 Chromium 浏览器（无头模式可选）
        self._browser = await self._playwright.chromium.launch(
            headless=False,  # 调试时可见，生产环境可改为 True
            args=[
                '--disable-blink-features=AutomationControlled',  # 防检测
            ]
        )

        # 创建浏览器上下文（注入 cookies）
        context = await self._browser.new_context()

        # 如果有 cookies，注入到上下文
        if self.cookies:
            await context.add_cookies([
                {
                    "name": name,
                    "value": value,
                    "domain": ".pinduoduo.com",
                    "path": "/",
                }
                for name, value in self.cookies.items()
            ])

        # 创建页面
        self._page = await context.new_page()

        # 导航到拼多多商家后台
        logger.info(f"正在导航到: {self.pdd_url}")
        await self._page.goto(self.pdd_url, wait_until="networkidle")

        logger.info("Playwright 初始化完成")

    async def _listen_for_messages(self):
        """
        监听拼多多商家后台的新消息

        ⚠️ 死循环监听逻辑，必须跑在隔离舱的独立事件循环中

        核心流程：
        1. 定期检查消息列表 DOM
        2. 提取新消息内容
        3. 通过 SignalBus 发送给主线程处理
        """
        logger.info("消息监听任务已启动")

        # 已处理的消息 ID 集合（避免重复处理）
        processed_messages: set = set()

        while self._running:
            try:
                # 等待消息列表加载
                await self._page.wait_for_selector(
                    ".message-list-item",  # 拼多多消息列表 CSS 选择器（需根据实际调整）
                    timeout=5000,
                    state="attached"
                )

                # 获取所有消息项
                message_items = await self._page.query_selector_all(".message-list-item")

                for item in message_items:
                    # 提取消息 ID（用于去重）
                    message_id = await item.get_attribute("data-message-id")
                    if message_id and message_id in processed_messages:
                        continue

                    # 提取用户 ID
                    user_id_elem = await item.query_selector(".user-id")
                    user_id = await user_id_elem.inner_text() if user_id_elem else "unknown"

                    # 提取消息内容
                    content_elem = await item.query_selector(".message-content")
                    raw_query = await content_elem.inner_text() if content_elem else ""

                    if message_id:
                        processed_messages.add(message_id)

                    # 发射新消息信号（通知主线程）
                    if raw_query:
                        logger.debug(f"检测到新消息: user_id={user_id}, content={raw_query[:50]}")
                        global_signal_bus.playwright_new_message_signal.emit(
                            self.shop_id,
                            user_id,
                            raw_query
                        )

                # 等待一段时间再检查（避免高频轮询）
                await asyncio.sleep(2)

            except asyncio.TimeoutError:
                # 消息列表未加载，继续等待
                logger.debug("等待消息列表加载...")
                await asyncio.sleep(5)

            except Exception as e:
                logger.warning(f"消息监听异常: {e}")
                await asyncio.sleep(3)

        logger.info("消息监听任务已停止")

    async def _consume_commands(self):
        """
        消费指令队列

        ⚠️ 必须跑在隔离舱的独立事件循环中

        核心流程：
        1. 从 queue.Queue 中取出指令（同步操作，安全）
        2. 根据指令类型执行相应操作
        3. ReplyCommand: 通过 Playwright 填入输入框并发送
        4. StopCommand: 停止循环
        """
        logger.info("指令消费任务已启动")

        while self._running:
            try:
                # 从队列中取出指令（非阻塞，带超时）
                try:
                    command = self._command_queue.get(timeout=1.0)
                except queue.Empty:
                    # 队列空，继续等待
                    await asyncio.sleep(0.5)
                    continue

                # 处理指令
                if isinstance(command, StopCommand):
                    logger.info(f"收到停止指令: {command.reason}")
                    self._running = False
                    break

                elif isinstance(command, ReplyCommand):
                    await self._send_reply_via_playwright(command)

                # 标记指令完成
                self._command_queue.task_done()

            except Exception as e:
                logger.exception(f"指令消费异常: {e}")
                await asyncio.sleep(1)

        logger.info("指令消费任务已停止")

    async def _send_reply_via_playwright(self, command: ReplyCommand):
        """
        通过 Playwright 发送回复

        Args:
            command: 回复指令
        """
        try:
            logger.debug(f"正在发送回复: user_id={command.user_id}")

            # 1. 找到输入框
            input_box = await self._page.query_selector(".reply-input-box")
            if not input_box:
                logger.warning("未找到回复输入框")
                global_signal_bus.playwright_reply_result_signal.emit(
                    command.shop_id,
                    command.user_id,
                    False,
                    "未找到回复输入框"
                )
                return

            # 2. 填入回复内容
            await input_box.fill(command.reply_text)

            # 3. 点击发送按钮
            send_btn = await self._page.query_selector(".send-button")
            if send_btn:
                await send_btn.click()

                # 4. 等待发送完成
                await asyncio.sleep(1)

                logger.info(f"回复已发送: user_id={command.user_id}")

                # 5. 报告发送成功
                global_signal_bus.playwright_reply_result_signal.emit(
                    command.shop_id,
                    command.user_id,
                    True,
                    ""
                )
            else:
                logger.warning("未找到发送按钮")
                global_signal_bus.playwright_reply_result_signal.emit(
                    command.shop_id,
                    command.user_id,
                    False,
                    "未找到发送按钮"
                )

        except Exception as e:
            logger.exception(f"发送回复失败: {e}")
            global_signal_bus.playwright_reply_result_signal.emit(
                command.shop_id,
                command.user_id,
                False,
                str(e)
            )

    def _cleanup(self):
        """
        清理 Playwright 资源

        ⚠️ 必须在隔离舱的独立事件循环中调用
        """
        async def _async_cleanup():
            try:
                if self._page:
                    await self._page.close()
                    logger.debug("页面已关闭")

                if self._browser:
                    await self._browser.close()
                    logger.debug("浏览器已关闭")

                if self._playwright:
                    await self._playwright.stop()
                    logger.debug("Playwright 已停止")

            except Exception as e:
                logger.warning(f"清理资源异常: {e}")

        # 在隔离舱的事件循环中执行清理
        if self._loop and not self._loop.is_closed():
            self._loop.run_until_complete(_async_cleanup())

        # 报告断开状态
        global_signal_bus.playwright_status_signal.emit(
            PlaywrightStatus.DISCONNECTED.value,
            "已断开"
        )


# =============================================================================
# Playwright 服务管理器
# =============================================================================

class PlaywrightServiceManager:
    """
    Playwright 服务管理器

    管理多个 PlaywrightWorkerThread 实例，每个店铺一个。

    使用示例：
        manager = PlaywrightServiceManager()

        # 启动店铺的 Playwright 监听
        manager.start_shop_listener(
            shop_id="12345",
            pdd_url="https://mms.pinduoduo.com/...",
            cookies={"cookie_name": "cookie_value"}
        )

        # 发送回复
        manager.send_reply("12345", "user1", "您好")

        # 停止监听
        manager.stop_shop_listener("12345")

        # 停止所有
        manager.stop_all()
    """

    def __init__(self):
        self._workers: dict = {}  # {shop_id: PlaywrightWorkerThread}
        logger.info("PlaywrightServiceManager 初始化完成")

    def start_shop_listener(
        self,
        shop_id: str,
        pdd_url: str,
        cookies: Optional[dict] = None
    ) -> bool:
        """
        启动店铺的 Playwright 监听

        Args:
            shop_id: 店铺ID
            pdd_url: 拼多多商家后台 URL
            cookies: 登录 cookies

        Returns:
            是否启动成功
        """
        if shop_id in self._workers:
            logger.warning(f"店铺 {shop_id} 的监听已在运行")
            return False

        try:
            worker = PlaywrightWorkerThread(
                shop_id=shop_id,
                pdd_url=pdd_url,
                cookies=cookies
            )

            self._workers[shop_id] = worker
            worker.start()

            logger.info(f"店铺 {shop_id} 的 Playwright 监听已启动")
            return True

        except Exception as e:
            logger.exception(f"启动店铺 {shop_id} 监听失败: {e}")
            return False

    def send_reply(self, shop_id: str, user_id: str, reply_text: str) -> bool:
        """
        发送回复

        Args:
            shop_id: 店铺ID
            user_id: 用户ID
            reply_text: 回复内容

        Returns:
            是否发送成功（入队成功）
        """
        if shop_id not in self._workers:
            logger.warning(f"店铺 {shop_id} 的监听未运行")
            return False

        worker = self._workers[shop_id]
        worker.send_reply(shop_id, user_id, reply_text)
        return True

    def stop_shop_listener(self, shop_id: str) -> bool:
        """
        停止店铺的 Playwright 监听

        Args:
            shop_id: 店铺ID

        Returns:
            是否停止成功
        """
        if shop_id not in self._workers:
            logger.warning(f"店铺 {shop_id} 的监听未运行")
            return False

        worker = self._workers[shop_id]
        worker.stop()

        # 等待线程结束
        if worker.isRunning():
            worker.wait(5000)

        # 清理引用
        del self._workers[shop_id]

        logger.info(f"店铺 {shop_id} 的 Playwright 监听已停止")
        return True

    def stop_all(self):
        """停止所有监听"""
        for shop_id, worker in self._workers.items():
            worker.stop()

        for worker in self._workers.values():
            if worker.isRunning():
                worker.wait(5000)

        self._workers.clear()
        logger.info("所有 Playwright 监听已停止")

    def is_running(self, shop_id: str) -> bool:
        """检查店铺监听是否在运行"""
        if shop_id not in self._workers:
            return False
        return self._workers[shop_id].isRunning()


# 全局单例
playwright_service_manager = PlaywrightServiceManager()


__all__ = [
    "PlaywrightStatus",
    "ReplyCommand",
    "StopCommand",
    "PlaywrightWorkerThread",
    "PlaywrightServiceManager",
    "playwright_service_manager",
]