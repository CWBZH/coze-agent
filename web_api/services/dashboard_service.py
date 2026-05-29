from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from web_api.schemas.dashboard import DashboardAlert, DashboardMetric, DashboardSummary
from web_api.services.schema_migration_service import SchemaMigrationService
from web_api.services.shop_service import ShopService
from web_api.services.sqlite_readonly import DEFAULT_DB_PATH, ReadOnlySqlite


class DashboardService:
    def __init__(self, db: ReadOnlySqlite | None = None, db_path: str | Path | None = None) -> None:
        configured = db_path or os.getenv("WEB_API_SQLITE_DB_PATH") or DEFAULT_DB_PATH
        self._db = db or ReadOnlySqlite(configured)
        self._db_path = Path(configured)

    def summary(self) -> DashboardSummary:
        SchemaMigrationService(self._db_path).migrate()
        shops, shop_warning = ShopService(self._db).list_shops()
        ai_enabled = self._count_ai_enabled()
        messages_24h = self._count_messages_24h()
        trace_counts = self._trace_counts()
        index_health = self._index_health()
        product_count = self._count_products()

        warnings = [value for value in (shop_warning, index_health.get("warning")) if value]
        warning = ";".join(warnings) if warnings else None
        return DashboardSummary(
            metrics=[
                DashboardMetric(key="shop_count", label="店铺总数", value=len(shops), caption="真实 shops/shop_auth 数据"),
                DashboardMetric(key="ai_enabled_count", label="启用 AI 店铺", value=ai_enabled, caption="shop_ai_settings 当前状态"),
                DashboardMetric(key="no_send", label="不发送模式", value="已启用", caption="PDD 真实发送关闭"),
                DashboardMetric(
                    key="rag_index_health",
                    label="RAG 索引健康度",
                    value=index_health["label"],
                    caption=f"商品知识 {product_count} 条，索引任务 {index_health['total']} 个",
                ),
                DashboardMetric(key="messages_24h", label="24 小时消息量", value=messages_24h, caption="真实 conversations 统计"),
                DashboardMetric(key="rag_hit_rate", label="RAG 命中率", value=trace_counts["hit_rate"], caption="真实 trace 统计；无数据时显示暂无"),
                DashboardMetric(key="llm_error_count", label="LLM 错误数", value=trace_counts["failed"], caption="真实 trace 统计"),
                DashboardMetric(key="guardrail_count", label="安全拦截数", value=trace_counts["guardrail_blocked"], caption="真实 trace 统计"),
            ],
            alerts=self._alerts(),
            system_status=[
                DashboardAlert(level="info", message="不发送真实消息 no_send"),
                DashboardAlert(level="warning", message="PDD 真实发送已关闭"),
                DashboardAlert(level="success", message="敏感授权不回显"),
                DashboardAlert(level="success", message="InternalEngine Web Admin 已启动"),
            ],
            warning=warning,
        )

    def _count_ai_enabled(self) -> int:
        count, _ = self._db.count(
            "SELECT COUNT(*) AS count FROM shop_ai_settings WHERE ai_enabled=1",
            required_tables=("shop_ai_settings",),
        )
        return count

    def _count_products(self) -> int:
        count, _ = self._db.count("SELECT COUNT(*) AS count FROM product_knowledge", required_tables=("product_knowledge",))
        return count

    def _count_messages_24h(self) -> int:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        count, _ = self._db.count(
            "SELECT COUNT(*) AS count FROM conversations WHERE updated_at >= ?",
            (since,),
            required_tables=("conversations",),
        )
        return count

    def _trace_counts(self) -> dict[str, Any]:
        result = self._db.query(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN answer_status IN ('failed', 'error') THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN guardrail_status IN ('blocked', 'transfer_to_human') THEN 1 ELSE 0 END) AS guardrail_blocked,
                SUM(CASE WHEN rag_hit_count > 0 THEN 1 ELSE 0 END) AS rag_hits
            FROM traces
            """,
            required_tables=("traces",),
        )
        if result.warning or not result.rows:
            return {"total": 0, "failed": 0, "guardrail_blocked": 0, "hit_rate": "暂无数据"}
        row = result.rows[0]
        total = int(row.get("total") or 0)
        hits = int(row.get("rag_hits") or 0)
        return {
            "total": total,
            "failed": int(row.get("failed") or 0),
            "guardrail_blocked": int(row.get("guardrail_blocked") or 0),
            "hit_rate": f"{round(hits * 100 / total)}%" if total else "暂无数据",
        }

    def _index_health(self) -> dict[str, Any]:
        result = self._db.query(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='succeeded' THEN 1 ELSE 0 END) AS succeeded,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                MAX(finished_at) AS last_finished_at
            FROM knowledge_index_jobs
            """,
            required_tables=("knowledge_index_jobs",),
        )
        if result.warning or not result.rows:
            return {"label": "未配置", "total": 0, "warning": result.warning}
        row = result.rows[0]
        total = int(row.get("total") or 0)
        failed = int(row.get("failed") or 0)
        succeeded = int(row.get("succeeded") or 0)
        if total == 0:
            label = "暂无索引"
        elif failed > 0 and succeeded == 0:
            label = "失败"
        elif failed > 0:
            label = "部分失败"
        else:
            label = "正常"
        return {"label": label, "total": total, "failed": failed, "succeeded": succeeded, "warning": None}

    def _alerts(self) -> list[DashboardAlert]:
        alerts: list[DashboardAlert] = []
        alerts.extend(
            self._latest_rows(
                """
                SELECT updated_at AS time, status, '商品同步任务 ' || id || '：' || status AS message
                FROM product_sync_jobs
                ORDER BY updated_at DESC
                LIMIT 3
                """,
                "product_sync_jobs",
            )
        )
        alerts.extend(
            self._latest_rows(
                """
                SELECT COALESCE(finished_at, started_at, created_at) AS time,
                       status,
                       '知识索引任务 ' || index_run_id || '：' || status AS message
                FROM knowledge_index_jobs
                ORDER BY COALESCE(finished_at, started_at, created_at) DESC
                LIMIT 3
                """,
                "knowledge_index_jobs",
            )
        )
        if not alerts:
            alerts.append(DashboardAlert(level="info", message="暂无真实运行提醒"))
        return alerts[:5]

    def _latest_rows(self, sql: str, table_name: str) -> list[DashboardAlert]:
        result = self._db.query(sql, required_tables=(table_name,))
        if result.warning:
            return []
        return [
            DashboardAlert(time=str(row.get("time") or ""), level=_alert_level(row.get("status")), message=str(row.get("message") or ""))
            for row in result.rows
        ]


def _alert_level(status: Any) -> str:
    text = str(status or "").lower()
    if text in {"succeeded", "active", "valid"}:
        return "success"
    if text in {"failed", "partial_failed", "expired", "cancelled"}:
        return "warning"
    return "info"
