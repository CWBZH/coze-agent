from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from web_api.schemas.dashboard import DashboardAlert, DashboardMetric, DashboardSummary
from web_api.services.schema_migration_service import SchemaMigrationService
from web_api.services.shop_service import ShopService
from web_api.services.sqlite_readonly import DEFAULT_DB_PATH, ReadOnlySqlite
from utils.pdd_send_policy import is_pdd_sending_enabled


class DashboardService:
    def __init__(self, db: ReadOnlySqlite | None = None, db_path: str | Path | None = None) -> None:
        configured = db_path or os.getenv("WEB_API_SQLITE_DB_PATH") or DEFAULT_DB_PATH
        self._db = db or ReadOnlySqlite(configured)
        self._db_path = Path(configured)

    def summary(self) -> DashboardSummary:
        SchemaMigrationService(self._db_path).migrate()
        shops, shop_warning = ShopService(self._db).list_shops()
        trace_counts = self._trace_counts()
        index_health = self._index_health()
        product_count = self._count_products()
        sync_counts = self._product_sync_counts()
        pdd_sending_enabled = is_pdd_sending_enabled()

        warnings = [value for value in (shop_warning, index_health.get("warning"), sync_counts.get("warning")) if value]
        return DashboardSummary(
            metrics=[
                DashboardMetric(
                    key="shop_count",
                    label="店铺总数",
                    value=len(shops),
                    caption="来自 shops/shop_auth 的真实店铺",
                ),
                DashboardMetric(
                    key="ai_enabled_count",
                    label="启用 InternalEngine",
                    value=self._count_ai_enabled(),
                    caption="shop_ai_settings 当前开启数",
                ),
                DashboardMetric(
                    key="pdd_sending",
                    label="PDD 发送状态",
                    value="真实发送已开启" if pdd_sending_enabled else "no-send",
                    caption="由 PDD_SENDING_ENABLED 控制",
                ),
                DashboardMetric(
                    key="rag_index_health",
                    label="RAG 索引健康度",
                    value=index_health["label"],
                    caption=f"商品知识 {product_count} 条，索引任务 {index_health['total']} 个",
                ),
                DashboardMetric(
                    key="messages_24h",
                    label="24 小时消息量",
                    value=self._count_messages_24h(),
                    caption="来自 conversations 的真实统计；无数据时为 0",
                ),
                DashboardMetric(
                    key="rag_hit_rate",
                    label="RAG 命中率",
                    value=trace_counts["hit_rate"],
                    caption="来自 traces 的真实统计；无数据时显示暂无数据",
                ),
                DashboardMetric(
                    key="llm_error_count",
                    label="LLM 错误数",
                    value=trace_counts["failed"],
                    caption="来自 traces 的 answer_status 失败统计",
                ),
                DashboardMetric(
                    key="guardrail_count",
                    label="安全拦截数",
                    value=trace_counts["guardrail_blocked"],
                    caption="来自 traces 的 guardrail_status 拦截统计",
                ),
                DashboardMetric(
                    key="product_sync_status",
                    label="商品同步任务",
                    value=sync_counts["label"],
                    caption=f"成功 {sync_counts['succeeded']}，失败 {sync_counts['failed']}，总计 {sync_counts['total']}",
                ),
            ],
            alerts=self._alerts(),
            system_status=[
                DashboardAlert(
                    level="warning" if pdd_sending_enabled else "info",
                    message="PDD 真实发送已开启" if pdd_sending_enabled else "不发送真实消息 no_send",
                ),
                DashboardAlert(level="success", message="密钥不回显"),
                DashboardAlert(level="success", message="InternalEngine Web Admin 已启动"),
            ],
            warning=";".join(warnings) if warnings else None,
        )

    def _count_ai_enabled(self) -> int:
        count, _ = self._db.count(
            "SELECT COUNT(*) AS count FROM shop_ai_settings WHERE ai_enabled=1",
            required_tables=("shop_ai_settings",),
        )
        return count

    def _count_products(self) -> int:
        if self._table_has_column("product_knowledge", "knowledge_status"):
            sql = """
            SELECT COUNT(*) AS count
            FROM product_knowledge
            WHERE COALESCE(knowledge_status, 'synced') != 'archived'
            """
        else:
            sql = "SELECT COUNT(*) AS count FROM product_knowledge"
        count, _ = self._db.count(sql, required_tables=("product_knowledge",))
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

    def _product_sync_counts(self) -> dict[str, Any]:
        result = self._db.query(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='succeeded' THEN 1 ELSE 0 END) AS succeeded,
                SUM(CASE WHEN status IN ('failed', 'partial_failed') THEN 1 ELSE 0 END) AS failed
            FROM product_sync_jobs
            """,
            required_tables=("product_sync_jobs",),
        )
        if result.warning or not result.rows:
            return {"label": "暂无任务", "total": 0, "succeeded": 0, "failed": 0, "warning": result.warning}
        row = result.rows[0]
        total = int(row.get("total") or 0)
        succeeded = int(row.get("succeeded") or 0)
        failed = int(row.get("failed") or 0)
        if total == 0:
            label = "暂无任务"
        elif failed > 0 and succeeded == 0:
            label = "失败"
        elif failed > 0:
            label = "部分失败"
        else:
            label = "正常"
        return {"label": label, "total": total, "succeeded": succeeded, "failed": failed, "warning": None}

    def _alerts(self) -> list[DashboardAlert]:
        alerts: list[DashboardAlert] = []
        alerts.extend(
            self._latest_rows(
                """
                SELECT updated_at AS time, status, '商品同步任务 ' || id || ': ' || status AS message
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
                       '知识索引任务 ' || index_run_id || ': ' || status AS message
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

    def _table_has_column(self, table_name: str, column_name: str) -> bool:
        result = self._db.query(f"PRAGMA table_info({table_name})")
        if result.warning:
            return False
        return any(str(row.get("name") or "") == column_name for row in result.rows)


def _alert_level(status: Any) -> str:
    text = str(status or "").lower()
    if text in {"succeeded", "active", "valid"}:
        return "success"
    if text in {"failed", "partial_failed", "expired", "cancelled"}:
        return "warning"
    return "info"
