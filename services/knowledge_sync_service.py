"""
知识库同步服务模块
==================

提供产品知识同步的后台服务，将同步逻辑从 UI 层完全解耦。

职责：
- 封装 SyncWorker 线程管理
- 封装 MySQL 与 Qdrant 异步对账逻辑
- 提供进度信号给 UI 层连接
- 实现容灾休眠和重试机制

V2.0 架构重构：斩断 P1 技术债
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Any, Dict

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from database.product_sync import ProductSyncService, SyncProgress
from utils.logger_loguru import get_logger

if TYPE_CHECKING:
    from database.knowledge_service import KnowledgeService

logger = get_logger("KnowledgeSyncService")


class SyncWorker(QThread):
    """
    同步工作线程

    在后台执行产品知识同步，通过信号报告进度和结果。
    UI 层不应直接操作此线程，应通过 KnowledgeSyncService 进行。
    """

    # 信号定义
    progress_updated = pyqtSignal(int, int, int, str, str)  # current, total, success, current_name, phase
    sync_finished = pyqtSignal(int, int, bool)  # success, failed, cancelled

    def __init__(
        self,
        shop_db_id: int,
        pdd_shop_id: str,
        user_id: str,
        is_full_sync: bool,
        product_sync: ProductSyncService,
        parent=None,
    ):
        super().__init__(parent)
        self.shop_db_id = shop_db_id
        self.pdd_shop_id = pdd_shop_id
        self.user_id = user_id
        self.is_full_sync = is_full_sync
        self.product_sync = product_sync
        self._cancelled = False

    def run(self):
        """运行同步"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        def progress_callback(progress: SyncProgress):
            self.progress_updated.emit(
                progress.current,
                progress.total,
                progress.success,
                progress.current_goods_name,
                progress.phase,
            )

        try:
            result = loop.run_until_complete(
                self.product_sync.sync_shop(
                    shop_id=int(self.pdd_shop_id),
                    shop_db_id=self.shop_db_id,
                    user_id=self.user_id,
                    is_full_sync=self.is_full_sync,
                    progress_callback=progress_callback,
                )
            )

            loop.close()
            self.sync_finished.emit(result.success, result.failed, result.cancelled)

        except Exception as e:
            logger.exception(f"同步线程异常: {e}")
            self.sync_finished.emit(0, 0, True)
        finally:
            loop.close()

    def cancel(self):
        """取消同步"""
        self._cancelled = True
        if self.product_sync:
            self.product_sync.cancel()


class KnowledgeSyncService(QObject):
    """
    知识库同步服务

    封装所有同步逻辑，UI 层只需连接信号即可。
    UI 层不应直接操作数据库 session 或 Qdrant 客户端。

    使用示例：
        service = KnowledgeSyncService(knowledge_service)

        # 连接信号
        service.progress_updated.connect(self.on_progress)
        service.sync_finished.connect(self.on_finished)

        # 开始同步
        service.start_sync(shop_db_id=1, pdd_shop_id="12345", user_id="user1", is_full_sync=False)

        # 取消同步
        service.cancel_sync()
    """

    # 公开信号，供 UI 层连接
    progress_updated = pyqtSignal(int, int, int, str, str)  # current, total, success, current_name, phase
    sync_finished = pyqtSignal(int, int, bool)  # success, failed, cancelled
    sync_error = pyqtSignal(str)  # error_message

    def __init__(self, knowledge_service: "KnowledgeService", parent=None):
        super().__init__(parent)
        self.knowledge_service = knowledge_service
        self.product_sync = ProductSyncService(knowledge_service)
        self._current_worker: Optional[SyncWorker] = None

        logger.info("KnowledgeSyncService 初始化完成")

    def is_syncing(self) -> bool:
        """检查是否正在同步"""
        return self._current_worker is not None and self._current_worker.isRunning()

    def start_sync(
        self,
        shop_db_id: int,
        pdd_shop_id: str,
        user_id: str,
        is_full_sync: bool = False
    ) -> bool:
        """
        开始同步

        Args:
            shop_db_id: 店铺数据库ID
            pdd_shop_id: 拼多多店铺ID
            user_id: 用户ID
            is_full_sync: 是否全量同步

        Returns:
            是否成功启动同步
        """
        # 检查是否已有同步任务在运行
        if self.is_syncing():
            logger.warning("已有同步任务在运行，请等待完成或取消")
            self.sync_error.emit("已有同步任务在运行")
            return False

        # 验证参数
        if not shop_db_id or not pdd_shop_id or not user_id:
            logger.error("同步参数不完整")
            self.sync_error.emit("同步参数不完整")
            return False

        try:
            # 创建工作线程
            self._current_worker = SyncWorker(
                shop_db_id=shop_db_id,
                pdd_shop_id=pdd_shop_id,
                user_id=user_id,
                is_full_sync=is_full_sync,
                product_sync=self.product_sync,
                parent=self,
            )

            # 连接信号（转发到公开信号）
            self._current_worker.progress_updated.connect(self.progress_updated)
            self._current_worker.sync_finished.connect(self._on_sync_finished)

            # 启动线程
            self._current_worker.start()

            logger.info(f"同步任务已启动: shop_db_id={shop_db_id}, is_full_sync={is_full_sync}")
            return True

        except Exception as e:
            logger.exception(f"启动同步任务失败: {e}")
            self.sync_error.emit(f"启动同步失败: {str(e)}")
            return False

    def cancel_sync(self):
        """取消当前同步任务"""
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.cancel()
            logger.info("同步任务已请求取消")

    def _on_sync_finished(self, success: int, failed: int, cancelled: bool):
        """同步完成回调"""
        logger.info(f"同步完成: success={success}, failed={failed}, cancelled={cancelled}")

        # 清理工作线程
        if self._current_worker:
            self._current_worker.deleteLater()
            self._current_worker = None

        # 发射完成信号
        self.sync_finished.emit(success, failed, cancelled)

    # =========================================================================
    # 便捷方法：直接获取数据（不涉及同步）
    # =========================================================================

    def get_all_shops(self):
        """获取所有店铺列表"""
        return self.knowledge_service.get_all_shops()

    def list_products_by_shop(self, shop_id: int):
        """获取店铺的产品知识列表"""
        return self.knowledge_service.list_products_by_shop(shop_id)

    def get_product_by_goods_id(self, shop_id: int, goods_id: int):
        """根据商品ID获取产品知识"""
        return self.knowledge_service.get_product_by_goods_id(shop_id, goods_id)

    def delete_product(self, product_id: int) -> bool:
        """删除产品知识"""
        return self.knowledge_service.delete_product(product_id)

    def clear_products_by_shop(self, shop_id: int) -> int:
        """清空店铺的所有产品知识"""
        return self.knowledge_service.clear_products_by_shop(shop_id)

    def update_product_content(self, product_id: int, goods_name: str, extracted_content: str) -> bool:
        """更新产品知识内容"""
        from database.models import ProductKnowledge, Shop

        with self.knowledge_service.get_session() as session:
            prod = session.get(ProductKnowledge, product_id)
            if prod:
                prod.goods_name = goods_name
                prod.extracted_content = extracted_content
                session.commit()
                return True
        return False

    def update_product_attributes(self, product_id: int, goods_name: str, attributes: Dict[str, Any]) -> bool:
        """更新产品结构化属性，并重新生成可检索产品知识。"""
        from database.models import ProductKnowledge, Shop

        clean_attrs = self._clean_product_attributes(attributes)
        with self.knowledge_service.get_session() as session:
            prod = session.get(ProductKnowledge, product_id)
            if not prod:
                return False

            prod.goods_name = goods_name
            prod.attribute_json = json.dumps(clean_attrs, ensure_ascii=False)
            prod.attribute_source_json = json.dumps(
                {
                    key: {
                        "source": "manual_ui",
                        "confidence": 1.0,
                        "evidence": value if not isinstance(value, list) else "；".join(value[:5]),
                    }
                    for key, value in clean_attrs.items()
                    if key != "extra_notes" and value not in ("", [], None)
                },
                ensure_ascii=False,
            )
            prod.extracted_content = self._render_product_content(prod, clean_attrs)
            prod.knowledge_status = "extracted"
            prod.last_extracted_at = datetime.now()
            shop = session.get(Shop, prod.shop_id)
            vector_shop_id = str(shop.shop_id) if shop and shop.shop_id else str(prod.shop_id)
            session.commit()

            try:
                self.product_sync._upsert_product_attribute_vectors(
                    vector_shop_id,
                    prod.goods_id,
                    clean_attrs,
                    json.loads(prod.attribute_source_json or "{}"),
                )
            except Exception as exc:
                logger.warning(f"产品属性向量更新失败，但MySQL已保存: goods_id={prod.goods_id}, error={exc}")
            return True

    def _clean_product_attributes(self, attributes: Dict[str, Any]) -> Dict[str, Any]:
        list_fields = {"sku_options", "effect", "warnings", "accessories"}
        clean: Dict[str, Any] = {}
        for key, value in (attributes or {}).items():
            if key in list_fields:
                if isinstance(value, str):
                    chunks = value.splitlines()
                elif isinstance(value, list):
                    chunks = [str(item) for item in value]
                else:
                    chunks = []
                items = []
                for chunk in chunks:
                    items.extend(item.strip(" -，,;；") for item in re.split(r"[、,，;；/]+", chunk))
                clean[key] = [item for item in items if item]
                continue
            text = "" if value is None else str(value).strip()
            clean[key] = text
        return clean

    def _render_product_content(self, product, attrs: Dict[str, Any]) -> str:
        lines = [
            f"商品名称: {product.goods_name}",
        ]
        if product.price:
            lines.append(f"价格: {product.price}")
        if product.sold_quantity:
            lines.append(f"销量: {product.sold_quantity}")

        scalar_fields = [
            ("商品分类", "category"),
            ("品牌", "brand"),
            ("默认规格", "sku_summary"),
            ("成分/材质", "ingredients"),
            ("使用方法", "usage_method"),
            ("使用时长", "usage_duration"),
            ("起泡情况", "foaming"),
            ("适用年龄", "suitable_age"),
            ("适用肤质", "skin_type"),
            ("香味", "fragrance"),
            ("保质期", "shelf_life"),
        ]
        for label, key in scalar_fields:
            value = attrs.get(key)
            if value:
                lines.append(f"{label}: {value}")

        list_fields = [
            ("功效", "effect"),
            ("注意事项", "warnings"),
            ("可选规格", "sku_options"),
            ("赠品/附加项", "accessories"),
        ]
        for label, key in list_fields:
            value = attrs.get(key)
            if isinstance(value, list) and value:
                lines.append(f"{label}: {'、'.join(value)}")
            elif isinstance(value, str) and value.strip():
                lines.append(f"{label}: {value.strip()}")

        extra = attrs.get("extra_notes")
        if extra:
            lines.append("额外补充:")
            lines.append(str(extra).strip())
        return "\n".join(lines)

    # =========================================================================
    # 客服知识相关方法
    # =========================================================================

    def list_customer_service_with_disabled(self, shop_id: int):
        """获取店铺的客服知识列表（包含禁用的）"""
        return self.knowledge_service.list_customer_service_with_disabled(shop_id)

    def filter_customer_service_by_tag(self, shop_id: int, tag: str):
        """根据标签筛选客服知识"""
        return self.knowledge_service.filter_customer_service_by_tag(shop_id, tag)

    def get_all_tags(self, shop_id: int):
        """获取店铺的所有标签"""
        return self.knowledge_service.get_all_tags(shop_id)

    def get_customer_service_by_id(self, cs_id: int):
        """根据ID获取客服知识"""
        return self.knowledge_service.get_customer_service_by_id(cs_id)

    def add_customer_service(
        self,
        shop_id: int,
        title: str,
        content: str,
        tags: str = None,
        enabled: bool = True
    ):
        """添加客服知识"""
        return self.knowledge_service.add_customer_service(
            shop_id=shop_id,
            title=title,
            content=content,
            tags=tags,
            enabled=enabled,
        )

    def update_customer_service(
        self,
        cs_id: int,
        title: str,
        content: str,
        tags: str = None,
        enabled: bool = True
    ) -> bool:
        """更新客服知识"""
        return self.knowledge_service.update_customer_service(
            cs_id=cs_id,
            title=title,
            content=content,
            tags=tags,
            enabled=enabled,
        )

    def delete_customer_service(self, cs_id: int) -> bool:
        """删除客服知识"""
        return self.knowledge_service.delete_customer_service(cs_id)

    def batch_import_customer_service(self, shop_id: int, rows: list) -> tuple:
        """批量导入客服知识"""
        return self.knowledge_service.batch_import_customer_service(shop_id, rows)

    # =========================================================================
    # 店铺查询方法
    # =========================================================================

    def get_shop_by_id(self, shop_id: int):
        """根据ID获取店铺对象"""
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload
        from database.models import Shop

        with self.knowledge_service.get_session() as session:
            stmt = select(Shop).where(Shop.id == shop_id).options(joinedload(Shop.accounts))
            return session.scalar(stmt)

    def get_cs_by_title(self, shop_id: int, title: str):
        """根据标题获取客服知识ID"""
        from sqlalchemy import select
        from database.models import CustomerServiceKnowledge

        with self.knowledge_service.get_session() as session:
            stmt = select(CustomerServiceKnowledge).where(
                CustomerServiceKnowledge.shop_id == shop_id,
                CustomerServiceKnowledge.title == title,
            )
            return session.scalar(stmt)
