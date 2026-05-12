"""
知识库向量同步工作线程

实现最终一致性架构：
- 死循环 + 休眠模式
- 每 5 秒扫描未向量化的知识记录
- 失败自动重试，永不崩溃
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional
from PyQt6.QtCore import QThread, pyqtSignal

from utils.logger_loguru import get_logger

if TYPE_CHECKING:
    from database.qdrant_manager import QdrantManager
    from database.db_manager import DBManager

logger = get_logger("AsyncKnowledgeSyncWorker")


class AsyncKnowledgeSyncWorker(QThread):
    """
    异步知识库向量同步工作线程

    核心逻辑（死循环 + 休眠）：
    1. 每隔 5 秒唤醒一次
    2. 查询 is_vectorized == False 且 enabled == True 的记录（最多 10 条）
    3. 调用 qdrant_manager.upsert_knowledge() 进行向量化
    4. 成功：更新 is_vectorized = True，commit
    5. 失败：打印 Error 日志，rollback，留给下次重试
    """

    # 信号定义
    sync_progress = pyqtSignal(int, int, str)  # current, total, status
    sync_success = pyqtSignal(int)  # knowledge_id
    sync_failed = pyqtSignal(int, str)  # knowledge_id, error_message

    # 同步间隔（秒）
    SYNC_INTERVAL = 5
    # 每批次处理数量
    BATCH_SIZE = 10

    def __init__(
        self,
        db_manager: 'DBManager',
        qdrant_manager: 'QdrantManager',
        parent=None,
    ):
        super().__init__(parent)
        self.db_manager = db_manager
        self.qdrant_manager = qdrant_manager
        self._running = True
        self._paused = False

    def run(self):
        """主循环：死循环 + 休眠"""
        logger.info("[SyncWorker] 启动知识库向量同步线程")

        while self._running:
            try:
                # 检查是否暂停
                if self._paused:
                    time.sleep(1)
                    continue

                # 执行同步
                self._sync_batch()

            except Exception as e:
                # 捕获所有异常，确保线程永不崩溃
                logger.error(f"[SyncWorker] 同步循环异常: {e}", exc_info=True)

            # 休眠 5 秒
            time.sleep(self.SYNC_INTERVAL)

        logger.info("[SyncWorker] 知识库向量同步线程已停止")

    def _sync_batch(self):
        """同步一批未向量化的知识"""
        from database.models import CustomerServiceKnowledge

        try:
            # 开启 MySQL 事务
            with self.db_manager.session_scope() as session:
                # 查询未向量化的知识（最多 10 条）
                pending_records = (
                    session.query(CustomerServiceKnowledge)
                    .filter(
                        CustomerServiceKnowledge.is_vectorized == False,
                        CustomerServiceKnowledge.enabled == True,
                    )
                    .limit(self.BATCH_SIZE)
                    .all()
                )

                if not pending_records:
                    logger.debug("[SyncWorker] 无待同步知识，继续休眠...")
                    return

                total = len(pending_records)
                logger.info(f"[SyncWorker] 发现 {total} 条待同步知识")

                # 遍历处理
                for i, record in enumerate(pending_records, 1):
                    try:
                        # 发送进度信号
                        self.sync_progress.emit(i, total, f"正在同步: {record.title}")

                        # 调用 Qdrant 向量化
                        success = self.qdrant_manager.upsert_knowledge(
                            shop_id=str(record.shop_id),
                            intent_domain="after_sales",  # 客服知识默认为售后域
                            question=record.title,
                            answer=record.content,
                            source="manual",
                            knowledge_id=str(record.id),
                        )

                        if success:
                            # 成功：更新标记
                            record.is_vectorized = True
                            session.commit()
                            logger.info(f"[SyncWorker] 知识同步成功: id={record.id}, title={record.title}")
                            self.sync_success.emit(record.id)
                        else:
                            # 失败：回滚，留给下次重试
                            session.rollback()
                            logger.error(f"[SyncWorker] 知识同步失败: id={record.id}, title={record.title}")
                            self.sync_failed.emit(record.id, "Qdrant 写入返回 False")

                    except Exception as e:
                        # 单条记录失败，不影响其他记录
                        session.rollback()
                        logger.error(f"[SyncWorker] 知识同步异常: id={record.id}, error={e}")
                        self.sync_failed.emit(record.id, str(e))

        except Exception as e:
            # 数据库查询失败
            logger.error(f"[SyncWorker] 查询待同步知识失败: {e}", exc_info=True)

    def stop(self):
        """停止同步线程"""
        logger.info("[SyncWorker] 正在停止同步线程...")
        self._running = False

    def pause(self):
        """暂停同步"""
        self._paused = True
        logger.info("[SyncWorker] 同步线程已暂停")

    def resume(self):
        """恢复同步"""
        self._paused = False
        logger.info("[SyncWorker] 同步线程已恢复")

    def trigger_immediate_sync(self):
        """触发立即同步（跳过休眠）"""
        logger.info("[SyncWorker] 触发立即同步")
        # 通过临时取消暂停来触发
        was_paused = self._paused
        self._paused = False
        # 下次循环会立即执行
