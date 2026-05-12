"""
拼多多协议服务模块 - WebSocket + HTTP API 隔离舱
=============================================

实现拼多多消息协议的 QThread 隔离舱，彻底解决双事件循环冲突。

核心设计：
- PDDProtocolWorkerThread: QThread 隔离舱，内部运行独立的 asyncio 事件循环
- WebSocket 监听: 实时接收拼多多商家后台消息
- HTTP API 发送: 通过 API 发送回复消息
- Cookie 管理: 复用 pdd_login.py 的登录逻辑

架构原则：
- 所有 WebSocket 和 HTTP 代码跑在隔离舱的独立事件循环中
- 主线程通过队列下发指令，不直接调用协议 API
- 隔离舱通过 SignalBus 向主线程报告状态和消息

V2.0 协议架构重构
"""
from __future__ import annotations

import asyncio
import json
import queue
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any, Set

import websockets
from websockets import exceptions as ws_exceptions

from PyQt6.QtCore import QThread, pyqtSignal

from ui.signal_bus import global_signal_bus
from utils.logger_loguru import get_logger

logger = get_logger("PDDProtocolService")


# =============================================================================
# 状态码定义
# =============================================================================

class PDDProtocolStatus(Enum):
    """拼多多协议状态码"""
    DISCONNECTED = 0      # 断开
    CONNECTING = 1        # 连接中
    CONNECTED = 2         # 已连接
    AUTHENTICATING = 3    # 认证中
    ERROR = 4             # 错误
    RECONNECTING = 5      # 重连中


# =============================================================================
# 指令数据结构
# =============================================================================

@dataclass
class ReplyCommand:
    """回复指令"""
    shop_id: str
    user_id: str
    recipient_uid: str
    reply_text: str
    timestamp: float


@dataclass
class StopCommand:
    """停止指令"""
    reason: str = "user_request"


# =============================================================================
# 重连配置
# =============================================================================

@dataclass
class ReconnectConfig:
    """重连配置"""
    enable_auto_reconnect: bool = True
    max_attempts: int = 10
    initial_delay: float = 1.0
    max_delay: float = 60.0
    backoff_factor: float = 2.0


# =============================================================================
# 拼多多协议隔离舱线程
# =============================================================================

class PDDProtocolWorkerThread(QThread):
    """
    拼多多协议工作线程隔离舱

    核心设计：
    1. run() 方法内创建独立的 asyncio.new_event_loop()
    2. WebSocket 监听跑在这个独立循环中
    3. HTTP API 发送通过 aiohttp 在同一循环中执行
    4. 通过 SignalBus 向主线程发送新消息和状态变化

    使用示例：
        worker = PDDProtocolWorkerThread(
            shop_id="12345",
            user_id="user1",
            cookies={"key": "value"}
        )

        # 连接信号
        global_signal_bus.playwright_new_message_signal.connect(self.on_new_message)
        global_signal_bus.playwright_status_signal.connect(self.on_status_change)

        # 启动线程
        worker.start()

        # 发送回复指令
        worker.send_reply("12345", "user1", "recipient_uid", "您好")

        # 停止线程
        worker.stop()
    """

    # API 版本号
    API_VERSION = "202506091557"

    def __init__(
        self,
        shop_id: str,
        user_id: str,
        cookies: Dict[str, str],
        reconnect_config: Optional[ReconnectConfig] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.shop_id = shop_id
        self.user_id = user_id
        self.cookies = cookies or {}

        # 重连配置
        self.reconnect_config = reconnect_config or ReconnectConfig()

        # 指令队列（主线程写入，隔离舱读取）
        self._command_queue: queue.Queue = queue.Queue()

        # 运行状态标志
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # WebSocket 对象
        self._ws: Optional[websockets.WebSocketClientProtocol] = None

        # 消息处理信号量（并发控制）
        self._message_semaphore: Optional[asyncio.Semaphore] = None
        self._processing_tasks: Set[asyncio.Task] = set()

        logger.info(f"PDDProtocolWorkerThread 初始化: shop_id={shop_id}, user_id={user_id}")

    # =========================================================================
    # 主线程调用接口（安全写入队列）
    # =========================================================================

    def send_reply(self, shop_id: str, user_id: str, recipient_uid: str, reply_text: str):
        """
        发送回复指令（主线程调用）

        Args:
            shop_id: 店铺ID
            user_id: 用户ID
            recipient_uid: 接收者UID
            reply_text: 回复内容
        """
        command = ReplyCommand(
            shop_id=shop_id,
            user_id=user_id,
            recipient_uid=recipient_uid,
            reply_text=reply_text,
            timestamp=time.time(),
        )
        self._command_queue.put(command)
        logger.debug(f"回复指令已入队: recipient_uid={recipient_uid}")

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
        线程主入口 - 创建独立事件循环并运行拼多多协议

        ⚠️ 关键设计：
        - 必须调用 asyncio.new_event_loop() 创建新循环
        - 所有 WebSocket 和 HTTP API 必须跑在这个循环中
        """
        # 1. 创建并设置独立的事件循环
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self._running = True
        self._message_semaphore = asyncio.Semaphore(50)  # 最大并发消息数

        logger.info("PDD 协议隔离舱事件循环已创建")

        try:
            # 2. 启动主循环（包含重连机制）
            self._loop.run_until_complete(self._main_loop())

        except Exception as e:
            logger.exception(f"PDD 协议隔离舱运行异常: {e}")
            global_signal_bus.playwright_status_signal.emit(
                PDDProtocolStatus.ERROR.value,
                str(e)
            )

        finally:
            # 3. 清理资源
            self._cleanup()
            self._loop.close()
            logger.info("PDD 协议隔离舱事件循环已关闭")

    async def _main_loop(self):
        """
        主循环 - 包含重连机制

        ⚠️ 核心流程：
        1. 获取 access_token
        2. 连接 WebSocket
        3. 启动消息监听和指令消费
        4. 断线后自动重连
        """
        attempt = 0

        while self._running:
            try:
                # 报告连接中状态
                if attempt > 0:
                    global_signal_bus.playwright_status_signal.emit(
                        PDDProtocolStatus.RECONNECTING.value,
                        f"正在重连 ({attempt}/{self.reconnect_config.max_attempts})"
                    )
                else:
                    global_signal_bus.playwright_status_signal.emit(
                        PDDProtocolStatus.CONNECTING.value,
                        "正在连接..."
                    )

                # 1. 获取 access_token
                access_token = await self._get_access_token()

                # 2. 连接 WebSocket
                await self._connect_and_run(access_token)

                # 正常退出（收到停止指令）
                break

            except Exception as e:
                logger.error(f"连接失败: {e}")

                if not self._running:
                    break

                attempt += 1
                if attempt >= self.reconnect_config.max_attempts:
                    logger.error("已达到最大重试次数")
                    global_signal_bus.playwright_status_signal.emit(
                        PDDProtocolStatus.ERROR.value,
                        f"连接失败，已重试 {attempt} 次"
                    )
                    break

                # 计算重连延迟（指数退避）
                delay = min(
                    self.reconnect_config.initial_delay * (self.reconnect_config.backoff_factor ** (attempt - 1)),
                    self.reconnect_config.max_delay
                )
                logger.info(f"{delay:.1f}秒后重试...")

                await asyncio.sleep(delay)

    async def _get_access_token(self) -> str:
        """
        获取 access_token

        ⚠️ 复用 pdd_login.py 的逻辑
        """
        from Channel.pinduoduo.utils.API.get_token import GetToken

        # 报告认证中状态
        global_signal_bus.playwright_status_signal.emit(
            PDDProtocolStatus.AUTHENTICATING.value,
            "正在认证..."
        )

        # 使用现有 cookies 获取 token
        token = GetToken(self.shop_id, self.user_id)
        access_token = token.get_token()

        if not access_token:
            raise ValueError("获取 access_token 失败，可能需要重新登录")

        logger.debug(f"access_token 获取成功: shop_id={self.shop_id}")
        return access_token

    async def _connect_and_run(self, access_token: str):
        """
        连接 WebSocket 并运行消息循环

        ⚠️ 参考 pdd_lifecycle.py 的 init() 方法
        """
        base_url = "wss://m-ws.pinduoduo.com/"

        # 构建连接参数
        params = {
            "access_token": access_token,
            "role": "mall_cs",
            "client": "web",
            "version": self.API_VERSION
        }
        query = "&".join([f"{k}={v}" for k, v in params.items()])
        full_url = f"{base_url}?{query}"

        logger.debug(f"正在连接到拼多多 WebSocket: shop_id={self.shop_id}")

        async with websockets.connect(
            full_url,
            ping_interval=60,
            ping_timeout=30,
            max_size=10**7,
            compression=None,
            close_timeout=10
        ) as websocket:
            self._ws = websocket
            logger.info(f"WebSocket 连接已建立: shop_id={self.shop_id}")

            # 报告已连接状态
            global_signal_bus.playwright_status_signal.emit(
                PDDProtocolStatus.CONNECTED.value,
                "已连接到拼多多商家后台"
            )

            # 创建三个并发任务：消息监听 + 心跳保活 + 指令消费
            listen_task = asyncio.create_task(self._message_loop(websocket))
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(websocket))  # P1 修复
            consume_task = asyncio.create_task(self._consume_commands())

            # 等待任务完成
            await asyncio.gather(
                listen_task,
                heartbeat_task,
                consume_task,
                return_exceptions=True
            )

    async def _message_loop(self, websocket):
        """
        消息监听循环

        ⚠️ 参考 pdd_lifecycle.py 的 _message_loop() 方法
        """
        try:
            logger.info(f"消息监听循环开始: shop_id={self.shop_id}")

            async for message in websocket:
                if not self._running:
                    logger.info("收到停止信号，退出消息循环")
                    break

                # 并发处理消息
                task = asyncio.create_task(
                    self._process_message(message)
                )
                self._processing_tasks.add(task)
                task.add_done_callback(self._processing_tasks.discard)

        except ws_exceptions.ConnectionClosed as e:
            logger.warning(f"WebSocket 连接关闭: code={e.code}, reason={e.reason}")
            raise
        except Exception as e:
            logger.error(f"消息循环异常: {e}")
            raise

    async def _heartbeat_loop(self, websocket):
        """
        心跳保活循环

        🔴 P1 修复：参考 pdd_lifecycle.py 的 _heartbeat_loop() 方法
        包含 3 次失败熔断逻辑
        """
        consecutive_failures = 0
        max_failures = 3
        heartbeat_interval = 30  # 30秒心跳间隔
        heartbeat_timeout = 10   # 10秒超时等待

        try:
            logger.info(f"心跳保活循环已启动: shop_id={self.shop_id}")

            while self._running:
                try:
                    # 发送 WebSocket 协议层 ping
                    start_time = asyncio.get_event_loop().time()
                    await websocket.ping()
                    response_time = asyncio.get_event_loop().time() - start_time

                    # 心跳成功，重置失败计数
                    consecutive_failures = 0
                    logger.debug(f"心跳成功，响应时间: {response_time:.3f}s")

                    # 等待下一次心跳
                    await asyncio.sleep(heartbeat_interval)

                except asyncio.TimeoutError:
                    consecutive_failures += 1
                    logger.warning(f"心跳超时，连续失败: {consecutive_failures}/{max_failures}")

                    if consecutive_failures >= max_failures:
                        logger.error("心跳连续失败3次，触发熔断，断开连接")
                        break

                    await asyncio.sleep(heartbeat_timeout)

                except Exception as e:
                    consecutive_failures += 1
                    logger.warning(f"心跳失败: {e}，连续失败: {consecutive_failures}/{max_failures}")

                    if consecutive_failures >= max_failures:
                        logger.error("心跳连续失败3次，触发熔断，断开连接")
                        break

                    await asyncio.sleep(heartbeat_timeout)

        except asyncio.CancelledError:
            logger.debug("心跳循环被取消")
        except Exception as e:
            logger.exception(f"心跳循环异常: {e}")
        finally:
            logger.info(f"心跳保活循环已结束: shop_id={self.shop_id}")

    async def _process_message(self, message: str):
        """
        处理单条消息

        ⚠️ 参考 pdd_message_handler.py 的 _process_websocket_message() 方法
        """
        async with self._message_semaphore:
            try:
                if not message or not message.strip():
                    return

                message_data = json.loads(message)

                # 提取消息类型
                msg_type = message_data.get("response", "unknown")

                # 只处理 push 类型的消息（用户消息）
                if msg_type != "push":
                    return

                # 提取发送者信息
                from_role = message_data.get("message", {}).get("from", {}).get("role", "")
                from_uid = message_data.get("message", {}).get("from", {}).get("uid", "")

                # 忽略客服自己发的消息
                if from_role == "mall_cs":
                    logger.debug(f"忽略客服消息: from_uid={from_uid}")
                    return

                # 提取消息内容
                user_msg_type = message_data.get("message", {}).get("type", 0)

                # 文本消息 (type=0)
                if user_msg_type == 0:
                    content = message_data.get("message", {}).get("content", "")
                # 图片消息 (type=1)
                elif user_msg_type == 1:
                    content = message_data.get("message", {}).get("content", "")
                    # 图片 URL，可以标记为图片消息
                else:
                    # 其他消息类型暂不处理
                    logger.debug(f"忽略非文本消息: type={user_msg_type}")
                    return

                if not content:
                    return

                # 提取接收者 UID（用于回复）
                to_uid = message_data.get("message", {}).get("to", {}).get("uid", "")

                logger.info(f"收到新消息: from_uid={from_uid}, content={content[:50]}")

                # 发射新消息信号（通知主线程）
                global_signal_bus.playwright_new_message_signal.emit(
                    self.shop_id,
                    from_uid,  # 使用 from_uid 作为 user_id
                    content
                )

            except json.JSONDecodeError:
                logger.error(f"JSON 解析失败: {message[:100]}")
            except Exception as e:
                logger.error(f"处理消息异常: {e}")

    async def _consume_commands(self):
        """
        消费指令队列

        ⚠️ 处理主线程下发的回复指令
        """
        logger.info("指令消费循环已启动")

        while self._running:
            try:
                # 从队列中取出指令（非阻塞，带超时）
                try:
                    command = self._command_queue.get(timeout=1.0)
                except queue.Empty:
                    await asyncio.sleep(0.5)
                    continue

                # 处理指令
                if isinstance(command, StopCommand):
                    logger.info(f"收到停止指令: {command.reason}")
                    self._running = False
                    break

                elif isinstance(command, ReplyCommand):
                    # 🔴 P0 修复：拟人化防封延迟（1.5-3.5秒随机）
                    import random
                    delay = random.uniform(1.5, 3.5)
                    logger.debug(f"拟人化延迟: {delay:.2f}秒")
                    await asyncio.sleep(delay)

                    await self._send_reply_via_api(command)

                # 标记指令完成
                self._command_queue.task_done()

            except Exception as e:
                logger.exception(f"指令消费异常: {e}")
                await asyncio.sleep(1)

        logger.info("指令消费循环已停止")

    async def _send_reply_via_api(self, command: ReplyCommand):
        """
        通过 HTTP API 发送回复

        ⚠️ 参考 send_message.py 的 send_text() 方法
        """
        import aiohttp

        try:
            logger.debug(f"正在发送回复: recipient_uid={command.recipient_uid}")

            url = "https://mms.pinduoduo.com/plateau/chat/send_message"

            # 构建请求数据
            data = {
                "data": {
                    "cmd": "send_message",
                    "request_id": self._generate_request_id(),
                    "message": {
                        "to": {
                            "role": "user",
                            "uid": command.recipient_uid
                        },
                        "from": {
                            "role": "mall_cs"
                        },
                        "content": command.reply_text,
                        "msg_id": None,
                        "type": 0,
                        "is_aut": 0,
                        "manual_reply": 1,
                    },
                },
                "client": "WEB"
            }

            # 构建请求头
            headers = {
                "Content-Type": "application/json;charset=UTF-8",
                "Origin": "https://mms.pinduoduo.com",
                "Referer": "https://mms.pinduoduo.com/chat-merchant/index.html",
            }

            # 添加 Cookie
            cookies = {k: v for k, v in self.cookies.items()}

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=data,
                    headers=headers,
                    cookies=cookies,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    result = await response.json()

                    if result.get("success"):
                        logger.info(f"回复发送成功: recipient_uid={command.recipient_uid}")

                        # 报告发送成功
                        global_signal_bus.playwright_reply_result_signal.emit(
                            command.shop_id,
                            command.recipient_uid,
                            True,
                            ""
                        )
                    else:
                        error_msg = result.get("result", {}).get("error", "未知错误")
                        error_code = result.get("result", {}).get("error_code", 0)

                        logger.error(f"回复发送失败: error_code={error_code}, error={error_msg}")

                        # 报告发送失败
                        global_signal_bus.playwright_reply_result_signal.emit(
                            command.shop_id,
                            command.recipient_uid,
                            False,
                            error_msg
                        )

                        # 如果是 Cookie 过期错误，触发重连
                        if error_code == 10002:
                            logger.warning("Cookie 可能已过期，需要重新认证")
                            raise ValueError("Cookie expired")

        except asyncio.TimeoutError:
            logger.error("发送回复超时")
            global_signal_bus.playwright_reply_result_signal.emit(
                command.shop_id,
                command.recipient_uid,
                False,
                "发送超时"
            )
        except Exception as e:
            logger.exception(f"发送回复异常: {e}")
            global_signal_bus.playwright_reply_result_signal.emit(
                command.shop_id,
                command.recipient_uid,
                False,
                str(e)
            )

    def _generate_request_id(self) -> str:
        """生成请求 ID"""
        import uuid
        return str(uuid.uuid4())

    def _cleanup(self):
        """清理资源"""
        try:
            # 关闭 WebSocket
            if self._ws and not self._ws.closed:
                asyncio.run_coroutine_threadsafe(
                    self._ws.close(),
                    self._loop
                )

            # 清理处理任务
            for task in self._processing_tasks:
                if not task.done():
                    task.cancel()

            logger.info("资源清理完成")

        except Exception as e:
            logger.warning(f"清理资源异常: {e}")

        # 报告断开状态
        global_signal_bus.playwright_status_signal.emit(
            PDDProtocolStatus.DISCONNECTED.value,
            "已断开"
        )


# =============================================================================
# 拼多多协议服务管理器
# =============================================================================

class PDDProtocolServiceManager:
    """
    拼多多协议服务管理器

    管理多个 PDDProtocolWorkerThread 实例，每个店铺一个。
    """

    def __init__(self):
        self._workers: Dict[str, PDDProtocolWorkerThread] = {}
        logger.info("PDDProtocolServiceManager 初始化完成")

    def start_shop_listener(
        self,
        shop_id: str,
        user_id: str,
        cookies: Dict[str, str],
        reconnect_config: Optional[ReconnectConfig] = None
    ) -> bool:
        """启动店铺的协议监听"""
        if shop_id in self._workers:
            logger.warning(f"店铺 {shop_id} 的监听已在运行")
            return False

        try:
            worker = PDDProtocolWorkerThread(
                shop_id=shop_id,
                user_id=user_id,
                cookies=cookies,
                reconnect_config=reconnect_config
            )

            self._workers[shop_id] = worker
            worker.start()

            logger.info(f"店铺 {shop_id} 的协议监听已启动")
            return True

        except Exception as e:
            logger.exception(f"启动店铺 {shop_id} 监听失败: {e}")
            return False

    def send_reply(self, shop_id: str, user_id: str, recipient_uid: str, reply_text: str) -> bool:
        """发送回复"""
        if shop_id not in self._workers:
            logger.warning(f"店铺 {shop_id} 的监听未运行")
            return False

        worker = self._workers[shop_id]
        worker.send_reply(shop_id, user_id, recipient_uid, reply_text)
        return True

    def stop_shop_listener(self, shop_id: str) -> bool:
        """停止店铺的协议监听"""
        if shop_id not in self._workers:
            logger.warning(f"店铺 {shop_id} 的监听未运行")
            return False

        worker = self._workers[shop_id]
        worker.stop()

        if worker.isRunning():
            worker.wait(5000)

        del self._workers[shop_id]

        logger.info(f"店铺 {shop_id} 的协议监听已停止")
        return True

    def stop_all(self):
        """停止所有监听"""
        for shop_id, worker in self._workers.items():
            worker.stop()

        for worker in self._workers.values():
            if worker.isRunning():
                worker.wait(5000)

        self._workers.clear()
        logger.info("所有协议监听已停止")

    def is_running(self, shop_id: str) -> bool:
        """检查店铺监听是否在运行"""
        if shop_id not in self._workers:
            return False
        return self._workers[shop_id].isRunning()


# 全局单例
pdd_protocol_service_manager = PDDProtocolServiceManager()


__all__ = [
    "PDDProtocolStatus",
    "ReplyCommand",
    "StopCommand",
    "ReconnectConfig",
    "PDDProtocolWorkerThread",
    "PDDProtocolServiceManager",
    "pdd_protocol_service_manager",
]