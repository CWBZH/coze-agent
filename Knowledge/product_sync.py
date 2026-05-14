"""商品同步服务 — 从拼多多 API 拉取商品列表"""
import asyncio
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass
from database.models import ProductKnowledge
from Channel.pinduoduo.utils.API.product_manager import ProductManager
from utils.logger_loguru import get_logger

logger = get_logger("ProductSync")


@dataclass
class SyncProgress:
    total: int = 0
    current: int = 0
    success: int = 0
    failed: int = 0
    current_goods_name: str = ""
    cancelled: bool = False
    phase: str = "fetching"


class ProductSyncService:
    def __init__(self, db_manager, request_delay: float = 1.0):
        self.db = db_manager
        self.request_delay = request_delay

    async def sync_shop(self, shop_id: str, shop_db_id: int, user_id: str,
                        progress_callback: Optional[Callable] = None) -> SyncProgress:
        pm = ProductManager(shop_id=shop_id, user_id=user_id)
        progress = SyncProgress()

        first_page = pm.get_product_list(page=1, size=20)
        if not first_page["success"]:
            progress.failed = 1
            return progress

        total = first_page["total"]
        progress.total = total

        all_products = []
        current_page = 1
        while True:
            page_result = pm.get_product_list(page=current_page, size=50)
            if not page_result["success"] or not page_result["products"]:
                break
            all_products.extend(page_result["products"])
            current_page += 1
            progress.current = len(all_products)
            if progress_callback:
                progress_callback(progress)
            await asyncio.sleep(self.request_delay)

        for idx, product in enumerate(all_products):
            goods_id = product.get("goods_id")
            goods_name = product.get("goods_name", f"goods_{goods_id}")
            progress.current = idx + 1
            progress.current_goods_name = goods_name

            existing = self._get_product(shop_db_id, goods_id)
            if existing:
                progress.success += 1
                continue

            try:
                detail = pm.get_product_detail(goods_id)
                await asyncio.sleep(self.request_delay)

                specifications = []
                raw_detail = None
                if detail["success"]:
                    product_info = detail["product_info"]
                    specs = product_info.get("specifications", [])
                    specifications = specs[:20] if isinstance(specs, list) else []
                    raw_detail = str(detail.get("product_info", {}))
                else:
                    raw_detail = str(product)

                self._save_product(
                    shop_db_id=shop_db_id,
                    goods_id=goods_id,
                    goods_name=goods_name,
                    price=product.get("price"),
                    price_min=product.get("price_min"),
                    price_max=product.get("price_max"),
                    sold_quantity=product.get("sold_quantity"),
                    thumb_url=product.get("thumb_url"),
                    specifications=str(specifications),
                    raw_detail_json=raw_detail
                )
                progress.success += 1
            except Exception as e:
                logger.error(f"同步商品失败 {goods_id}: {e}")
                progress.failed += 1

            if progress_callback:
                progress_callback(progress)

        return progress

    def _get_product(self, shop_db_id: int, goods_id: str):
        with self.db.session_scope() as session:
            return session.query(ProductKnowledge).filter(
                ProductKnowledge.shop_id == shop_db_id,
                ProductKnowledge.goods_id == str(goods_id)
            ).first()

    def _save_product(self, shop_db_id: int, goods_id: str, goods_name: str, **kwargs):
        with self.db.session_scope() as session:
            product = ProductKnowledge(
                shop_id=shop_db_id,
                goods_id=str(goods_id),
                goods_name=goods_name,
                **{k: v for k, v in kwargs.items() if v is not None}
            )
            session.add(product)
