from fastapi import HTTPException

from web_api.schemas.shops import ShopDetail, ShopSummary
from web_api.services.sqlite_readonly import ReadOnlySqlite


class ShopService:
    def __init__(self, db: ReadOnlySqlite | None = None) -> None:
        self._db = db or ReadOnlySqlite()

    def list_shops(self) -> tuple[list[ShopSummary], str | None]:
        result = self._db.query(
            """
            SELECT
                s.id AS db_shop_id,
                s.shop_id AS shop_id,
                s.shop_name AS shop_name,
                c.channel_name AS channel_name,
                MAX(a.status) AS account_status,
                MAX(conv.updated_at) AS last_activity
            FROM shops s
            LEFT JOIN channels c ON c.id = s.channel_id
            LEFT JOIN accounts a ON a.shop_id = s.id
            LEFT JOIN conversations conv ON conv.shop_id = s.id
            GROUP BY s.id, s.shop_id, s.shop_name, c.channel_name
            ORDER BY s.id ASC
            """,
            required_tables=("shops",),
        )
        shops = [self._row_to_summary(row) for row in result.rows]
        return shops, result.warning

    def get_shop(self, shop_id: str) -> ShopDetail:
        result = self._db.query(
            """
            SELECT
                s.id AS db_shop_id,
                s.shop_id AS shop_id,
                s.shop_name AS shop_name,
                c.channel_name AS channel_name,
                MAX(a.status) AS account_status,
                MAX(conv.updated_at) AS last_activity
            FROM shops s
            LEFT JOIN channels c ON c.id = s.channel_id
            LEFT JOIN accounts a ON a.shop_id = s.id
            LEFT JOIN conversations conv ON conv.shop_id = s.id
            WHERE s.shop_id = ?
            GROUP BY s.id, s.shop_id, s.shop_name, c.channel_name
            LIMIT 1
            """,
            (shop_id,),
            required_tables=("shops",),
        )
        if result.warning:
            raise HTTPException(status_code=404, detail={"status": "not_found", "warning": result.warning})
        if not result.rows:
            raise HTTPException(status_code=404, detail={"status": "not_found", "shop_id": shop_id})
        row = result.rows[0]
        product_count, count_warning = self._db.count(
            "SELECT COUNT(*) AS count FROM product_knowledge WHERE shop_id = ?",
            (row["db_shop_id"],),
            required_tables=("product_knowledge",),
        )
        shop = self._row_to_summary(row)
        return ShopDetail(
            shop_id=shop.shop_id,
            shop_name=shop.shop_name,
            channel=shop.channel,
            internal_engine_summary={
                "internal_enabled": shop.internal_enabled,
                "rag_enabled": shop.rag_enabled,
                "llm_enabled": shop.llm_enabled,
                "intent_classifier_enabled": shop.intent_classifier_enabled,
                "answer_generator_enabled": shop.answer_generator_enabled,
                "no_send": True,
            },
            product_knowledge_count=product_count,
            sop_coverage={
                "product_catalog": "from_product_knowledge",
                "logistics_policy": "mock",
                "after_sales_evidence": "mock",
                "promotion_policy": "mock",
                "sensitive_user_safety": "mock",
                "redline_escalation": "direct_transfer",
            },
            rag_index_status={
                "product_version": "real-product-v1",
                "sop_version": "sop-test-v1",
                "status": "mock_until_pgvector_api",
            },
            recent_trace_summary={
                "total": 0,
                "failed": 0,
                "guardrail_blocked": 0,
                "last_status": "not_connected",
            },
            warning=count_warning,
        )

    @staticmethod
    def _row_to_summary(row: dict) -> ShopSummary:
        return ShopSummary(
            shop_id=str(row.get("shop_id") or ""),
            shop_name=str(row.get("shop_name") or ""),
            channel="PDD",
            internal_enabled=True,
            rag_enabled=True,
            llm_enabled=True,
            intent_classifier_enabled=True,
            answer_generator_enabled=True,
            account_status=_account_status(row.get("account_status")),
            websocket_status="unknown",
            no_send=True,
            shadow_enabled=False,
            last_activity=str(row.get("last_activity") or "") or None,
        )


def _account_status(value: object) -> str:
    if value in (1, "1", True):
        return "active"
    if value in (0, "0", False):
        return "inactive"
    if value is None:
        return "unknown"
    return str(value)
