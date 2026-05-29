import sqlite3
from typing import Any

from fastapi import HTTPException

from web_api.schemas.shops import ShopDetail, ShopSummary
from web_api.services.sqlite_readonly import ReadOnlySqlite


class ShopService:
    def __init__(self, db: ReadOnlySqlite | None = None) -> None:
        self._db = db or ReadOnlySqlite()

    def list_shops(self) -> tuple[list[ShopSummary], str | None]:
        archive_clause = "AND COALESCE(s.archived_at, '') = ''" if self._table_has_column("shops", "archived_at") else ""
        result = self._db.query(
            f"""
            SELECT
                s.id AS db_shop_id,
                s.shop_id AS shop_id,
                s.shop_name AS shop_name,
                'pinduoduo' AS channel_name
            FROM shops s
            WHERE s.shop_id NOT LIKE 'remote%'
              {archive_clause}
            ORDER BY s.id ASC
            """,
            required_tables=("shops",),
        )
        shops = []
        seen_shop_ids: set[str] = set()
        for row in result.rows:
            enriched = dict(row)
            shop_id = str(enriched.get("shop_id") or "")
            if not shop_id or shop_id in seen_shop_ids:
                continue
            seen_shop_ids.add(shop_id)
            enriched["account_status"] = self._account_status_for_shop(enriched.get("db_shop_id"), enriched.get("shop_id"))
            enriched["last_activity"] = self._last_activity_for_shop(enriched.get("db_shop_id"), enriched.get("shop_id"))
            shops.append(self._row_to_summary(enriched))
        if not shops:
            shops = self._list_auth_backfilled_shops()
        return shops, result.warning

    def get_shop(self, shop_id: str) -> ShopDetail:
        archive_clause = "AND COALESCE(s.archived_at, '') = ''" if self._table_has_column("shops", "archived_at") else ""
        result = self._db.query(
            f"""
            SELECT
                s.id AS db_shop_id,
                s.shop_id AS shop_id,
                s.shop_name AS shop_name,
                'pinduoduo' AS channel_name
            FROM shops s
            WHERE s.shop_id = ?
              AND s.shop_id NOT LIKE 'remote%'
              {archive_clause}
            LIMIT 1
            """,
            (shop_id,),
            required_tables=("shops",),
        )
        if result.warning:
            raise HTTPException(status_code=404, detail={"status": "not_found", "warning": result.warning})
        if not result.rows:
            raise HTTPException(status_code=404, detail={"status": "not_found", "shop_id": shop_id})
        row = dict(result.rows[0])
        row["account_status"] = self._account_status_for_shop(row.get("db_shop_id"), row.get("shop_id"))
        row["last_activity"] = self._last_activity_for_shop(row.get("db_shop_id"), row.get("shop_id"))
        shop = self._row_to_summary(row)
        product_count, count_warning = self._db.count(
            "SELECT COUNT(*) AS count FROM product_knowledge WHERE CAST(shop_id AS TEXT) IN (?, ?)",
            (str(row["db_shop_id"]), shop.shop_id),
            required_tables=("product_knowledge",),
        )
        active_versions = self._active_version_summary(shop.shop_id)
        index_status = self._index_status(shop.shop_id)
        trace_summary = self._trace_summary(row["db_shop_id"], shop.shop_id)
        sop_coverage = self._sop_coverage(shop.shop_id, product_count, active_versions)
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
            sop_coverage=sop_coverage,
            rag_index_status=index_status,
            recent_trace_summary=trace_summary,
            warning=count_warning,
        )

    def _list_auth_backfilled_shops(self) -> list[ShopSummary]:
        result = self._db.query(
            """
            SELECT
                sa.shop_id AS shop_id,
                COALESCE(NULLIF(sa.safe_display, ''), sa.shop_id) AS shop_name,
                sa.platform AS channel_name,
                sa.auth_status AS account_status,
                sa.updated_at AS last_activity
            FROM shop_auth sa
            WHERE sa.shop_id NOT LIKE 'remote%'
              AND sa.auth_status = 'valid'
            ORDER BY sa.updated_at DESC
            """,
            required_tables=("shop_auth",),
        )
        return [self._row_to_summary(row) for row in result.rows]

    def _table_has_column(self, table_name: str, column_name: str) -> bool:
        if not self._db.db_path.exists():
            return False
        try:
            with sqlite3.connect(f"file:{self._db.db_path.resolve().as_posix()}?mode=ro", uri=True) as conn:
                return any(row[1] == column_name for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall())
        except sqlite3.Error:
            return False

    def _account_status_for_shop(self, db_shop_id: Any, platform_shop_id: Any) -> Any:
        result = self._db.query(
            """
            SELECT MAX(status) AS account_status
            FROM accounts
            WHERE CAST(shop_id AS TEXT) IN (?, ?)
            """,
            (str(db_shop_id), str(platform_shop_id)),
            required_tables=("accounts",),
        )
        if result.warning or not result.rows:
            auth_result = self._db.query(
                """
                SELECT auth_status AS account_status
                FROM shop_auth
                WHERE shop_id = ? AND auth_status = 'valid'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (str(platform_shop_id),),
                required_tables=("shop_auth",),
            )
            if auth_result.warning or not auth_result.rows:
                return None
            return auth_result.rows[0].get("account_status")
        return result.rows[0].get("account_status")

    def _last_activity_for_shop(self, db_shop_id: Any, platform_shop_id: Any) -> Any:
        result = self._db.query(
            """
            SELECT MAX(updated_at) AS last_activity
            FROM conversations
            WHERE CAST(shop_id AS TEXT) IN (?, ?)
            """,
            (str(db_shop_id), str(platform_shop_id)),
            required_tables=("conversations",),
        )
        if result.warning or not result.rows:
            auth_result = self._db.query(
                """
                SELECT MAX(updated_at) AS last_activity
                FROM shop_auth
                WHERE shop_id = ?
                """,
                (str(platform_shop_id),),
                required_tables=("shop_auth",),
            )
            if auth_result.warning or not auth_result.rows:
                return None
            return auth_result.rows[0].get("last_activity")
        return result.rows[0].get("last_activity")

    def _active_version_summary(self, shop_id: str) -> dict[str, Any]:
        result = self._db.query(
            """
            SELECT source_type, domain, COUNT(*) AS count, MAX(activated_at) AS last_activated_at
            FROM knowledge_versions
            WHERE shop_id=? AND is_active=1
            GROUP BY source_type, domain
            """,
            (shop_id,),
            required_tables=("knowledge_versions",),
        )
        if result.warning:
            return {"warning": result.warning, "total_active": 0, "domains": {}}
        domains: dict[str, Any] = {}
        total = 0
        for row in result.rows:
            key = f"{row.get('source_type')}:{row.get('domain')}"
            count = int(row.get("count") or 0)
            total += count
            domains[key] = {
                "count": count,
                "last_activated_at": row.get("last_activated_at"),
            }
        return {"total_active": total, "domains": domains}

    def _index_status(self, shop_id: str) -> dict[str, Any]:
        result = self._db.query(
            """
            SELECT status, source_type, source_id, domain, version, chunk_count, embedded_count, indexed_count, finished_at, error_summary
            FROM knowledge_index_jobs
            WHERE shop_id=?
            ORDER BY COALESCE(finished_at, started_at, created_at) DESC, id DESC
            LIMIT 1
            """,
            (shop_id,),
            required_tables=("knowledge_index_jobs",),
        )
        if result.warning:
            return {"status": "missing", "warning": result.warning}
        if not result.rows:
            return {"status": "missing", "summary": "暂无真实索引任务"}
        row = result.rows[0]
        return {
            "status": row.get("status") or "unknown",
            "source_type": row.get("source_type"),
            "source_id": row.get("source_id"),
            "domain": row.get("domain"),
            "version": row.get("version"),
            "chunk_count": int(row.get("chunk_count") or 0),
            "embedded_count": int(row.get("embedded_count") or 0),
            "indexed_count": int(row.get("indexed_count") or 0),
            "finished_at": row.get("finished_at"),
            "error_summary": row.get("error_summary"),
        }

    def _trace_summary(self, db_shop_id: Any, platform_shop_id: Any) -> dict[str, Any]:
        result = self._db.query(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN answer_status IN ('failed', 'error') THEN 1 ELSE 0 END) AS failed,
                   SUM(CASE WHEN guardrail_action IN ('blocked', 'transfer_to_human') THEN 1 ELSE 0 END) AS guardrail_blocked,
                   MAX(created_at) AS last_activity
            FROM traces
            WHERE CAST(shop_id AS TEXT) IN (?, ?)
            """,
            (str(db_shop_id), str(platform_shop_id)),
            required_tables=("traces",),
        )
        if result.warning:
            return {"total": 0, "failed": 0, "guardrail_blocked": 0, "last_activity": None, "warning": result.warning}
        row = result.rows[0] if result.rows else {}
        return {
            "total": int(row.get("total") or 0),
            "failed": int(row.get("failed") or 0),
            "guardrail_blocked": int(row.get("guardrail_blocked") or 0),
            "last_activity": row.get("last_activity"),
        }

    @staticmethod
    def _sop_coverage(shop_id: str, product_count: int, active_versions: dict[str, Any]) -> dict[str, Any]:
        domains = active_versions.get("domains") if isinstance(active_versions, dict) else {}
        return {
            "product_catalog": "available" if product_count > 0 else "missing",
            "active_version_count": int(active_versions.get("total_active") or 0) if isinstance(active_versions, dict) else 0,
            "active_domains": domains or {},
            "logistics_policy": "available" if "sop:logistics_policy" in (domains or {}) else "missing",
            "after_sales_evidence": "available" if "sop:after_sales" in (domains or {}) else "missing",
            "promotion_policy": "available" if "sop:promotion_policy" in (domains or {}) else "missing",
            "sensitive_user_safety": "available" if "sop:sensitive_user_safety" in (domains or {}) else "missing",
            "redline_escalation": "direct_transfer",
        }

    @staticmethod
    def _row_to_summary(row: dict) -> ShopSummary:
        channel_name = str(row.get("channel_name") or "pdd").lower()
        return ShopSummary(
            shop_id=str(row.get("shop_id") or ""),
            shop_name=str(row.get("shop_name") or ""),
            channel="PDD" if channel_name in ("pdd", "pinduoduo") else str(row.get("channel_name") or "unknown"),
            internal_enabled=False,
            rag_enabled=False,
            llm_enabled=False,
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
