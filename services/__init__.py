"""
服务层模块

提供业务逻辑服务，实现 UI 层与底层存储的解耦。

V2.0 Playwright 集成：
- PlaywrightWorkerThread: 隔离舱线程，独立事件循环
- PlaywrightServiceManager: 多店铺监听管理
- PlaywrightBridge: 主线程桥接控制器

V2.0 拼多多协议集成：
- PDDProtocolWorkerThread: WebSocket/HTTP 协议隔离舱
- PDDProtocolServiceManager: 多店铺协议管理
"""
from services.knowledge_sync_service import KnowledgeSyncService
from services.playwright_service import (
    PlaywrightWorkerThread,
    PlaywrightServiceManager,
    playwright_service_manager,
    PlaywrightStatus,
)
from services.playwright_bridge import (
    PlaywrightBridge,
    create_playwright_bridge,
)
from services.pdd_protocol_service import (
    PDDProtocolWorkerThread,
    PDDProtocolServiceManager,
    pdd_protocol_service_manager,
)

__all__ = [
    "KnowledgeSyncService",
    "PlaywrightWorkerThread",
    "PlaywrightServiceManager",
    "playwright_service_manager",
    "PlaywrightStatus",
    "PlaywrightBridge",
    "create_playwright_bridge",
    "PDDProtocolWorkerThread",
    "PDDProtocolServiceManager",
    "pdd_protocol_service_manager",
]