import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from web_api.schemas.shops import ShopDetail, ShopSummary
from web_api.services.provider_status_service import ProviderStatusService
from web_api.services.sqlite_readonly import ReadOnlySqlite
from utils.pdd_send_policy import is_pdd_sending_enabled


class ShopService:
    def __init__(self, db: ReadOnlySqlite | None = None) -> None:
        self._db = db or ReadOnlySqlite()
        self._provider_status_cache: dict[str, Any] | None = None
        self._worker_status_cache: dict[str, Any] | None | bool = False

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
            enriched.update(self._runtime_flags_for_shop(shop_id))
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
        row.update(self._runtime_flags_for_shop(str(row.get("shop_id") or "")))
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
                "no_send": shop.no_send,
                "websocket_status": shop.websocket_status,
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
        candidates: list[Any] = []
        result = self._db.query(
            """
            SELECT MAX(updated_at) AS last_activity
            FROM conversations
            WHERE CAST(shop_id AS TEXT) IN (?, ?)
            """,
            (str(db_shop_id), str(platform_shop_id)),
            required_tables=("conversations",),
        )
        if not result.warning and result.rows:
            candidates.append(result.rows[0].get("last_activity"))

        auth_result = self._db.query(
            """
            SELECT MAX(updated_at) AS last_activity
            FROM shop_auth
            WHERE shop_id = ?
            """,
            (str(platform_shop_id),),
            required_tables=("shop_auth",),
        )
        if not auth_result.warning and auth_result.rows:
            candidates.append(auth_result.rows[0].get("last_activity"))

        inbound_result = self._db.query(
            """
            SELECT MAX(updated_at) AS last_activity
            FROM pdd_inbound_message_queue
            WHERE CAST(shop_id AS TEXT) = ?
            """,
            (str(platform_shop_id),),
            required_tables=("pdd_inbound_message_queue",),
        )
        if not inbound_result.warning and inbound_result.rows:
            candidates.append(inbound_result.rows[0].get("last_activity"))

        outbox_result = self._db.query(
            """
            SELECT MAX(updated_at) AS last_activity
            FROM pdd_reply_outbox
            WHERE CAST(shop_id AS TEXT) = ?
            """,
            (str(platform_shop_id),),
            required_tables=("pdd_reply_outbox",),
        )
        if not outbox_result.warning and outbox_result.rows:
            candidates.append(outbox_result.rows[0].get("last_activity"))

        return self._latest_activity(candidates)

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
            "after_sales_evidence": "available" if "sop:after_sales_evidence" in (domains or {}) else "missing",
            "promotion_policy": "available" if "sop:promotion_policy" in (domains or {}) else "missing",
            "sensitive_user_safety": "available" if "sop:sensitive_user_safety" in (domains or {}) else "missing",
            "redline_escalation": "direct_transfer",
        }

    def _runtime_flags_for_shop(self, shop_id: str) -> dict[str, Any]:
        ai_enabled = self._shop_ai_enabled(shop_id)
        provider_status = self._provider_status()
        pgvector_ready = self._provider_ready(provider_status, "pgvector")
        embedding_ready = self._provider_ready(provider_status, "embedding")
        llm_ready = self._provider_ready(provider_status, "llm")
        pdd_sending = is_pdd_sending_enabled()
        worker_status = self._worker_status_for_shop(shop_id)
        active_versions = self._active_version_summary(shop_id)
        has_active_knowledge = int(active_versions.get("total_active") or 0) > 0 if isinstance(active_versions, dict) else False
        return {
            "internal_enabled": ai_enabled,
            "rag_enabled": ai_enabled and pgvector_ready and embedding_ready and has_active_knowledge,
            "llm_enabled": ai_enabled and llm_ready,
            "intent_classifier_enabled": ai_enabled and llm_ready,
            "answer_generator_enabled": ai_enabled and llm_ready,
            "websocket_status": worker_status.get("websocket_status") or "unknown",
            "worker_status": worker_status.get("status") or "unknown",
            "no_send": not pdd_sending,
            "shadow_enabled": False,
        }

    def _provider_status(self) -> dict[str, Any]:
        if self._provider_status_cache is None:
            self._provider_status_cache = ProviderStatusService().get_status().model_dump()
        return self._provider_status_cache

    @staticmethod
    def _provider_ready(provider_status: dict[str, Any], provider_name: str) -> bool:
        providers = provider_status.get("providers") if isinstance(provider_status, dict) else {}
        state = providers.get(provider_name) if isinstance(providers, dict) else {}
        if not isinstance(state, dict):
            return False
        return bool(state.get("configured")) and str(state.get("status") or "") == "configured"

    def _shop_ai_enabled(self, shop_id: str) -> bool:
        result = self._db.query(
            "SELECT ai_enabled FROM shop_ai_settings WHERE shop_id=? LIMIT 1",
            (str(shop_id),),
            required_tables=("shop_ai_settings",),
        )
        if result.warning or not result.rows:
            return False
        return bool(result.rows[0].get("ai_enabled"))

    def _worker_status_for_shop(self, shop_id: str) -> dict[str, Any]:
        payload = self._load_worker_status_payload()
        if not payload:
            return {"status": "unknown", "websocket_status": "unknown"}
        status = str(payload.get("computed_status") or payload.get("worker_status") or payload.get("worker_state") or "unknown")
        accounts = [
            item for item in payload.get("accounts", [])
            if isinstance(item, dict) and str(item.get("shop_id") or "") == str(shop_id)
        ]
        connections = [
            item for item in payload.get("connections", [])
            if isinstance(item, dict) and str(item.get("shop_id") or "") == str(shop_id)
        ]
        account_running = any(str(item.get("state") or "").lower() == "running" for item in accounts)
        connected = any(str(item.get("state") or "").lower() == "connected" for item in connections)
        if status == "running" and account_running:
            shop_status = "running"
        elif status in {"missing", "invalid", "stale", "stopped"}:
            shop_status = status
        else:
            shop_status = "stopped"
        if connected and status == "running":
            websocket_status = "connected"
        elif connected:
            websocket_status = "stale"
        else:
            websocket_status = "unknown"
        return {"status": shop_status, "websocket_status": websocket_status}

    def _load_worker_status_payload(self) -> dict[str, Any] | None:
        if self._worker_status_cache is not False:
            return self._worker_status_cache if isinstance(self._worker_status_cache, dict) else None
        path = self._worker_status_path()
        if not path.exists():
            self._worker_status_cache = None
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"computed_status": "invalid", "worker_status": "invalid", "status_file_path": str(path)}
        if not isinstance(payload, dict):
            payload = {"computed_status": "invalid", "worker_status": "invalid", "status_file_path": str(path)}
        updated_at = payload.get("updated_at")
        computed_status = "running"
        try:
            if updated_at is None or time.time() - float(updated_at) > 60:
                computed_status = "stale"
        except (TypeError, ValueError):
            computed_status = "stale"
        if payload.get("shutdown_completed_at"):
            computed_status = "stopped"
        payload["computed_status"] = computed_status
        payload["worker_status"] = computed_status
        self._worker_status_cache = payload
        return payload

    def _worker_status_path(self) -> Path:
        configured = os.getenv("WORKER_STATUS_PATH")
        if configured:
            return Path(configured)
        return self._db.db_path.parent / "runtime" / "worker_status.json"

    @staticmethod
    def _latest_activity(values: list[Any]) -> str | None:
        parsed: list[tuple[float, str]] = []
        for value in values:
            normalized = ShopService._normalize_activity(value)
            if not normalized:
                continue
            parsed.append(normalized)
        if not parsed:
            return None
        parsed.sort(key=lambda item: item[0], reverse=True)
        return parsed[0][1]

    @staticmethod
    def _normalize_activity(value: Any) -> tuple[float, str] | None:
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            try:
                dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                return None
            return (dt.timestamp(), dt.isoformat())
        text = str(value).strip()
        if not text:
            return None
        try:
            numeric = float(text)
        except ValueError:
            numeric = None
        if numeric is not None:
            try:
                dt = datetime.fromtimestamp(numeric, tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                return None
            return (dt.timestamp(), dt.isoformat())
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return (0.0, text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt.timestamp(), text)

    def _row_to_summary(self, row: dict) -> ShopSummary:
        channel_name = str(row.get("channel_name") or "pdd").lower()
        return ShopSummary(
            shop_id=str(row.get("shop_id") or ""),
            shop_name=str(row.get("shop_name") or ""),
            channel="PDD" if channel_name in ("pdd", "pinduoduo") else str(row.get("channel_name") or "unknown"),
            internal_enabled=bool(row.get("internal_enabled")),
            rag_enabled=bool(row.get("rag_enabled")),
            llm_enabled=bool(row.get("llm_enabled")),
            intent_classifier_enabled=bool(row.get("intent_classifier_enabled")),
            answer_generator_enabled=bool(row.get("answer_generator_enabled")),
            account_status=_account_status(row.get("account_status")),
            websocket_status=str(row.get("websocket_status") or "unknown"),
            no_send=bool(row.get("no_send", True)),
            shadow_enabled=bool(row.get("shadow_enabled")),
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
