"""商品同步服务 — 从拼多多 API 拉取商品列表"""
import asyncio
import json
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
        user_id, cookies = self._resolve_account(shop_id, user_id)
        pm = ProductManager(shop_id=shop_id, user_id=user_id, cookies=cookies)
        progress = SyncProgress()

        first_page = pm.get_product_list(page=1, size=20)
        if not first_page["success"]:
            progress.failed = 1
            progress.current_goods_name = first_page.get("error_msg", "获取商品列表失败")
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

    def _resolve_user_id(self, shop_id: str, user_id: str) -> str:
        resolved_user_id, _cookies = self._resolve_account(shop_id, user_id)
        return resolved_user_id

    def _resolve_account(self, shop_id: str, user_id: str) -> tuple[str, dict]:
        if user_id:
            account = self._find_account(shop_id, str(user_id))
            return str(user_id), self._parse_cookies(account.get("cookies") if account else None)

        accounts = self.db.get_accounts_by_shop("pinduoduo", str(shop_id))
        if not accounts:
            logger.error(f"同步商品失败: 店铺 {shop_id} 没有可用账号，无法加载 cookies")
            return "", {}

        online_accounts = [account for account in accounts if account.get("status") == 1]
        account = online_accounts[0] if online_accounts else accounts[0]
        resolved_user_id = str(account.get("user_id") or "")
        cookies = self._parse_cookies(account.get("cookies"))
        logger.info(
            f"商品同步自动选择账号: shop_id={shop_id}, user_id={resolved_user_id}, "
            f"username={account.get('username')}, status={account.get('status')}, "
            f"cookie_keys={len(cookies)}"
        )
        return resolved_user_id, cookies

    def _find_account(self, shop_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        for account in self.db.get_accounts_by_shop("pinduoduo", str(shop_id)):
            if str(account.get("user_id")) == str(user_id):
                return account
        return None

    @staticmethod
    def _parse_cookies(cookies_data) -> dict:
        if isinstance(cookies_data, dict):
            return cookies_data
        if isinstance(cookies_data, str) and cookies_data.strip():
            try:
                data = json.loads(cookies_data)
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                logger.error("同步商品失败: 账号 cookies 不是合法 JSON")
        return {}

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
