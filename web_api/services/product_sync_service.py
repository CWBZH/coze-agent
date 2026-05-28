from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from web_api.services.shop_auth_resolver import ShopAuthResolution, ShopAuthResolver
from web_api.services.sqlite_readonly import DEFAULT_DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_error(value: object) -> str:
    text = str(value or "")
    lowered = text.lower()
    if any(word in lowered for word in ("cookie", "token", "password", "authorization", "secret")):
        return "redacted_auth_error"
    return text[:500]


class ProductSyncService:
    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        auth_resolver: ShopAuthResolver | None = None,
        product_manager_factory: Callable[[str, str | None, dict[str, str]], Any] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.auth_resolver = auth_resolver or ShopAuthResolver(self.db_path)
        self.product_manager_factory = product_manager_factory or self._default_product_manager_factory

    def init_schema(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "deploy" / "sql" / "product_sync_jobs_schema.sql"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.executescript(schema_path.read_text(encoding="utf-8"))
            self._ensure_product_knowledge_columns(conn)
            conn.commit()
        finally:
            conn.close()

    def create_job(self, shop_id: str, *, mode: str = "full", operator: str = "local_admin", limit: int | None = None) -> dict[str, Any]:
        self.init_schema()
        auth = self.auth_resolver.get_cookies(shop_id, platform="pdd")
        if auth.status != "ok" or not auth.cookies:
            raise ValueError("auth_required")
        now = _now()
        job_id = f"psync-{uuid.uuid4().hex[:12]}"
        conn = self._connect()
        try:
            internal_shop_id = self._internal_shop_id(conn, shop_id)
            conn.execute(
                """
                INSERT INTO product_sync_jobs
                    (id, shop_id, internal_shop_id, status, mode, created_by, created_at, updated_at)
                VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (job_id, shop_id, internal_shop_id, mode, operator, now, now),
            )
            conn.commit()
        finally:
            conn.close()
        self._run_job(job_id, shop_id, limit=limit)
        return self.get_job(shop_id, job_id)

    def list_jobs(self, shop_id: str, limit: int = 50) -> list[dict[str, Any]]:
        self.init_schema()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM product_sync_jobs WHERE shop_id=? ORDER BY updated_at DESC LIMIT ?",
                (shop_id, limit),
            ).fetchall()
            return [self._job_row(row) for row in rows]
        finally:
            conn.close()

    def get_job(self, shop_id: str, job_id: str) -> dict[str, Any]:
        self.init_schema()
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM product_sync_jobs WHERE shop_id=? AND id=?", (shop_id, job_id)).fetchone()
            if row is None:
                raise KeyError(job_id)
            payload = self._job_row(row)
            items = conn.execute(
                "SELECT * FROM product_sync_job_items WHERE shop_id=? AND job_id=? ORDER BY updated_at DESC",
                (shop_id, job_id),
            ).fetchall()
            payload["items"] = [dict(item) for item in items]
            return payload
        finally:
            conn.close()

    def retry_failed_items(self, shop_id: str, job_id: str) -> dict[str, Any]:
        self.init_schema()
        conn = self._connect()
        try:
            failed_items = conn.execute(
                "SELECT goods_id, goods_name FROM product_sync_job_items WHERE shop_id=? AND job_id=? AND status='failed'",
                (shop_id, job_id),
            ).fetchall()
        finally:
            conn.close()
        self._run_job(job_id, shop_id, retry_goods=[str(row["goods_id"]) for row in failed_items if row["goods_id"]])
        return self.get_job(shop_id, job_id)

    def coverage(self, shop_id: str) -> dict[str, Any]:
        self.init_schema()
        conn = self._connect()
        try:
            internal_shop_id = self._internal_shop_id(conn, shop_id)
            rows = conn.execute(
                """
                SELECT price, price_min, price_max, specifications, usage, ingredients, shelf_life, warnings,
                       manual_notes, raw_detail_json, updated_at
                FROM product_knowledge WHERE shop_id=?
                """,
                (internal_shop_id,),
            ).fetchall()
            counters = {
                "shop_id": shop_id,
                "total": len(rows),
                "has_price": 0,
                "has_specs": 0,
                "has_usage": 0,
                "has_ingredients": 0,
                "has_shelf_life": 0,
                "has_warnings": 0,
                "has_manual_notes": 0,
                "last_sync_at": None,
                "warning": "pending_real_shop_id" if shop_id.startswith("remote-") else None,
            }
            for row in rows:
                raw = self._json(row["raw_detail_json"])
                counters["has_price"] += int(bool(row["price"] or row["price_min"] or row["price_max"] or self._pick(raw, "price", "goods_price")))
                counters["has_specs"] += int(bool(row["specifications"] or self._pick(raw, "specs", "specifications", "sku_options")))
                counters["has_usage"] += int(bool(row["usage"] or self._pick(raw, "usage", "usage_method", "how_to_use")))
                counters["has_ingredients"] += int(bool(row["ingredients"] or self._pick(raw, "ingredients", "ingredient", "composition")))
                counters["has_shelf_life"] += int(bool(row["shelf_life"] or self._pick(raw, "shelf_life", "expiry", "expiration")))
                counters["has_warnings"] += int(bool(row["warnings"] or self._pick(raw, "warnings", "warning", "notice", "cautions")))
                counters["has_manual_notes"] += int(bool(row["manual_notes"] or self._pick(raw, "manual_notes", "notes")))
                if row["updated_at"]:
                    counters["last_sync_at"] = max(str(counters["last_sync_at"] or ""), str(row["updated_at"])) or None
            return counters
        finally:
            conn.close()

    def _run_job(self, job_id: str, shop_id: str, *, limit: int | None = None, retry_goods: list[str] | None = None) -> None:
        now = _now()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE product_sync_jobs SET status='running', started_at=COALESCE(started_at, ?), updated_at=? WHERE id=? AND shop_id=?",
                (now, now, job_id, shop_id),
            )
            conn.commit()
        finally:
            conn.close()

        auth = self.auth_resolver.get_cookies(shop_id, platform="pdd")
        if auth.status != "ok" or not auth.cookies:
            self._finish_job(job_id, shop_id, status="failed", error_summary="auth_required")
            return

        try:
            manager = self.product_manager_factory(shop_id, auth.user_id, auth.cookies)
            products = self._fetch_products(manager, limit=limit, retry_goods=retry_goods)
        except Exception as exc:
            self._finish_job(job_id, shop_id, status="failed", error_summary=_sanitize_error(exc))
            return

        succeeded = failed = skipped = 0
        total = len(products)
        for product in products:
            goods_id = str(product.get("goods_id") or product.get("goodsId") or "")
            goods_name = str(product.get("goods_name") or product.get("goodsName") or "")
            item_id = f"psync-item-{uuid.uuid4().hex[:12]}"
            self._upsert_item(item_id, job_id, shop_id, goods_id, goods_name, "running")
            if not goods_id:
                skipped += 1
                self._upsert_item(item_id, job_id, shop_id, goods_id, goods_name, "skipped", "goods_id_missing")
                continue
            try:
                detail = manager.get_product_detail(goods_id)
                if not detail or not detail.get("success"):
                    raise RuntimeError(detail.get("error_msg") if isinstance(detail, dict) else "detail_failed")
                self._upsert_product_knowledge(shop_id, product, detail)
                succeeded += 1
                self._upsert_item(item_id, job_id, shop_id, goods_id, goods_name, "succeeded")
            except Exception as exc:
                failed += 1
                self._upsert_item(item_id, job_id, shop_id, goods_id, goods_name, "failed", _sanitize_error(exc))

        status = "succeeded" if failed == 0 else "partial_failed" if succeeded else "failed"
        coverage = self.coverage(shop_id)
        self._finish_job(
            job_id,
            shop_id,
            status=status,
            total_count=total,
            succeeded_count=succeeded,
            failed_count=failed,
            skipped_count=skipped,
            coverage_json=coverage,
            error_summary=None if failed == 0 else "some_items_failed",
        )

    def _fetch_products(self, manager: Any, *, limit: int | None, retry_goods: list[str] | None) -> list[dict[str, Any]]:
        if retry_goods:
            return [{"goods_id": goods_id, "goods_name": ""} for goods_id in retry_goods]
        first = manager.get_product_list(page=1, size=min(limit or 50, 50))
        if not first or not first.get("success"):
            raise RuntimeError(first.get("error_msg") if isinstance(first, dict) else "product_list_failed")
        products = list(first.get("products") or [])
        if limit:
            return products[:limit]
        total = int(first.get("total") or len(products))
        page = 2
        while len(products) < total:
            page_result = manager.get_product_list(page=page, size=50)
            if not page_result or not page_result.get("success") or not page_result.get("products"):
                break
            products.extend(page_result.get("products") or [])
            page += 1
        return products

    def _upsert_product_knowledge(self, platform_shop_id: str, product: dict[str, Any], detail: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            internal_shop_id = self._internal_shop_id(conn, platform_shop_id)
            product_info = detail.get("product_info") if isinstance(detail, dict) else {}
            product_info = product_info if isinstance(product_info, dict) else {}
            goods_id = str(product.get("goods_id") or product.get("goodsId") or product_info.get("goods_id") or "")
            raw = {"list_item": product, "detail": product_info}
            now = _now()
            values = {
                "shop_id": internal_shop_id,
                "goods_id": goods_id,
                "goods_name": str(product.get("goods_name") or product_info.get("goods_name") or ""),
                "price": self._text(product.get("price") or product_info.get("price")),
                "price_min": self._text(product.get("price_min")),
                "price_max": self._text(product.get("price_max")),
                "sold_quantity": product.get("sold_quantity"),
                "thumb_url": self._text(product.get("thumb_url")),
                "specifications": self._json_text(product_info.get("specifications") or product.get("specifications")),
                "usage": self._text(product_info.get("usage") or product_info.get("usage_method")),
                "ingredients": self._text(product_info.get("ingredients")),
                "shelf_life": self._text(product_info.get("shelf_life")),
                "warnings": self._text(product_info.get("warnings") or product_info.get("notice")),
                "manual_notes": self._text(product_info.get("manual_notes")),
                "raw_detail_json": json.dumps(raw, ensure_ascii=False),
                "knowledge_status": "synced",
                "created_at": now,
                "updated_at": now,
            }
            existing = conn.execute(
                "SELECT id FROM product_knowledge WHERE shop_id=? AND goods_id=? LIMIT 1",
                (internal_shop_id, goods_id),
            ).fetchone()
            if existing:
                update_columns = [column for column in values if column not in {"shop_id", "goods_id", "created_at"}]
                conn.execute(
                    f"UPDATE product_knowledge SET {', '.join(f'{column}=?' for column in update_columns)} WHERE id=?",
                    [values[column] for column in update_columns] + [existing["id"]],
                )
            else:
                columns = list(values.keys())
                placeholders = ", ".join("?" for _ in columns)
                conn.execute(
                    f"INSERT INTO product_knowledge ({', '.join(columns)}) VALUES ({placeholders})",
                    [values[column] for column in columns],
                )
            conn.commit()
        finally:
            conn.close()

    def _upsert_item(self, item_id: str, job_id: str, shop_id: str, goods_id: str, goods_name: str, status: str, error: str | None = None) -> None:
        now = _now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO product_sync_job_items
                    (id, job_id, shop_id, goods_id, goods_name, status, error_summary, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status, error_summary=excluded.error_summary, updated_at=excluded.updated_at
                """,
                (item_id, job_id, shop_id, goods_id, goods_name, status, error, now, now),
            )
            conn.commit()
        finally:
            conn.close()

    def _finish_job(self, job_id: str, shop_id: str, **updates: Any) -> None:
        now = _now()
        fields = {"updated_at": now, "finished_at": now, **updates}
        if "coverage_json" in fields and isinstance(fields["coverage_json"], dict):
            fields["coverage_json"] = json.dumps(fields["coverage_json"], ensure_ascii=False)
        conn = self._connect()
        try:
            assignments = ", ".join(f"{key}=?" for key in fields)
            conn.execute(
                f"UPDATE product_sync_jobs SET {assignments} WHERE id=? AND shop_id=?",
                [*fields.values(), job_id, shop_id],
            )
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _default_product_manager_factory(shop_id: str, user_id: str | None, cookies: dict[str, str]) -> Any:
        from Channel.pinduoduo.utils.API.product_manager import ProductManager

        return ProductManager(shop_id=shop_id, user_id=user_id, cookies=cookies)

    def _internal_shop_id(self, conn: sqlite3.Connection, platform_shop_id: str) -> int:
        conn.execute("INSERT OR IGNORE INTO channels (channel_name, description) VALUES ('pinduoduo', 'PDD')")
        channel_id = int(conn.execute("SELECT id FROM channels WHERE channel_name='pinduoduo'").fetchone()["id"])
        conn.execute(
            "INSERT OR IGNORE INTO shops (channel_id, shop_id, shop_name, created_at) VALUES (?, ?, ?, ?)",
            (channel_id, platform_shop_id, platform_shop_id, _now()),
        )
        return int(conn.execute("SELECT id FROM shops WHERE channel_id=? AND shop_id=?", (channel_id, platform_shop_id)).fetchone()["id"])

    def _ensure_product_knowledge_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(product_knowledge)").fetchall()}
        desired = {
            "price_min": "TEXT",
            "price_max": "TEXT",
            "sold_quantity": "INTEGER",
            "thumb_url": "TEXT",
            "usage": "TEXT",
            "ingredients": "TEXT",
            "shelf_life": "TEXT",
            "warnings": "TEXT",
            "manual_notes": "TEXT",
            "knowledge_status": "TEXT DEFAULT 'synced'",
        }
        for column, column_type in desired.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE product_knowledge ADD COLUMN {column} {column_type}")

    def _job_row(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["coverage_json"] = self._json(payload.get("coverage_json"))
        return payload

    @staticmethod
    def _json(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            parsed = json.loads(str(value))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _pick(raw: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = raw.get(key)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _text(value: Any) -> str:
        return "" if value is None else str(value)

    @staticmethod
    def _json_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)
