import hashlib
import json
import math
import os
import re
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from web_api.services.sqlite_readonly import DEFAULT_DB_PATH, parse_json_list_or_text, parse_json_object, pick_text


SCHEMA_PATH = Path("deploy/sql/knowledge_center_schema.sql")


def init_knowledge_center_schema(db_path: str | Path | None = None) -> None:
    KnowledgeCenterRepository(db_path).init_schema()


class KnowledgeCenterRepository:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or DEFAULT_DB_PATH)

    def init_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.commit()

    def create_sop(
        self,
        shop_id: str,
        domain: str,
        title: str,
        content: str,
        *,
        actor: str = "local_admin",
    ) -> dict[str, Any]:
        now = _now()
        content_hash = _hash_json({"shop_id": shop_id, "domain": domain, "title": title, "content": content})
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO knowledge_sop
                (shop_id, domain, title, content, status, content_hash, created_by, updated_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)
                """,
                (shop_id, domain, title, content, content_hash, actor, actor, now, now),
            )
            conn.commit()
            return self.get_sop(int(cursor.lastrowid), conn=conn)

    def update_sop(self, sop_id: int, *, title: str | None = None, content: str | None = None, actor: str = "local_admin") -> dict[str, Any]:
        current = self.get_sop(sop_id)
        new_title = current["title"] if title is None else title
        new_content = current["content"] if content is None else content
        content_hash = _hash_json(
            {"shop_id": current["shop_id"], "domain": current["domain"], "title": new_title, "content": new_content}
        )
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_sop
                SET title=?, content=?, content_hash=?, updated_by=?, updated_at=?
                WHERE id=?
                """,
                (new_title, new_content, content_hash, actor, now, sop_id),
            )
            conn.commit()
            return self.get_sop(sop_id, conn=conn)

    def get_sop(self, sop_id: int, *, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        row = self._fetch_one("SELECT * FROM knowledge_sop WHERE id=?", (sop_id,), conn=conn)
        if not row:
            raise KeyError(f"sop_not_found:{sop_id}")
        return row

    def list_sop(
        self,
        *,
        shop_id: str | None = None,
        domain: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if shop_id:
            where.append("shop_id=?")
            params.append(shop_id)
        if domain:
            where.append("domain=?")
            params.append(domain)
        if status:
            where.append("status=?")
            params.append(status)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        return self._fetch_all(f"SELECT * FROM knowledge_sop {where_sql} ORDER BY updated_at DESC, id DESC", tuple(params))

    def archive_sop(self, sop_id: int, *, actor: str = "local_admin") -> dict[str, Any]:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE knowledge_sop SET status='archived', updated_by=?, updated_at=? WHERE id=?",
                (actor, now, sop_id),
            )
            conn.commit()
            return self.get_sop(sop_id, conn=conn)

    def get_override(self, shop_id: str, goods_id: str) -> dict[str, Any] | None:
        return self._fetch_one(
            "SELECT * FROM product_manual_overrides WHERE shop_id=? AND goods_id=?",
            (shop_id, goods_id),
        )

    def upsert_override(
        self,
        shop_id: str,
        goods_id: str,
        *,
        goods_name: str | None = None,
        usage_override: str | None = None,
        ingredients_override: str | None = None,
        warnings_override: str | None = None,
        shelf_life_override: str | None = None,
        manual_notes: str | None = None,
        specs_override: str | None = None,
        price_note_override: str | None = None,
        actor: str = "local_admin",
    ) -> dict[str, Any]:
        now = _now()
        payload = {
            "shop_id": shop_id,
            "goods_id": goods_id,
            "goods_name": goods_name or "",
            "usage_override": usage_override or "",
            "ingredients_override": ingredients_override or "",
            "warnings_override": warnings_override or "",
            "shelf_life_override": shelf_life_override or "",
            "manual_notes": manual_notes or "",
            "specs_override": specs_override or "",
            "price_note_override": price_note_override or "",
        }
        content_hash = _hash_json(payload)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO product_manual_overrides
                (
                    shop_id, goods_id, goods_name, usage_override, ingredients_override, warnings_override,
                    shelf_life_override, manual_notes, specs_override, price_note_override, status,
                    content_hash, created_by, updated_by, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)
                ON CONFLICT(shop_id, goods_id) DO UPDATE SET
                    goods_name=excluded.goods_name,
                    usage_override=excluded.usage_override,
                    ingredients_override=excluded.ingredients_override,
                    warnings_override=excluded.warnings_override,
                    shelf_life_override=excluded.shelf_life_override,
                    manual_notes=excluded.manual_notes,
                    specs_override=excluded.specs_override,
                    price_note_override=excluded.price_note_override,
                    status='draft',
                    content_hash=excluded.content_hash,
                    updated_by=excluded.updated_by,
                    updated_at=excluded.updated_at
                """,
                (
                    shop_id,
                    goods_id,
                    payload["goods_name"],
                    payload["usage_override"],
                    payload["ingredients_override"],
                    payload["warnings_override"],
                    payload["shelf_life_override"],
                    payload["manual_notes"],
                    payload["specs_override"],
                    payload["price_note_override"],
                    content_hash,
                    actor,
                    actor,
                    now,
                    now,
                ),
            )
            conn.commit()
        result = self.get_override(shop_id, goods_id)
        if not result:
            raise RuntimeError("override_upsert_failed")
        return result

    def get_product_raw(self, shop_id: str, goods_id: str, *, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        row = self._fetch_one(
            "SELECT * FROM product_knowledge WHERE shop_id=? AND goods_id=? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (shop_id, goods_id),
            conn=conn,
        )
        if not row and self._table_exists("shops", conn=conn):
            row = self._fetch_one(
                """
                SELECT pk.*
                FROM product_knowledge pk
                JOIN shops s ON s.id = pk.shop_id
                WHERE s.shop_id=? AND pk.goods_id=?
                ORDER BY pk.updated_at DESC, pk.id DESC
                LIMIT 1
                """,
                (shop_id, goods_id),
                conn=conn,
            )
        if not row:
            raise KeyError(f"product_not_found:{shop_id}:{goods_id}")
        return row

    def create_version_and_job(
        self,
        *,
        shop_id: str,
        source_type: str,
        source_id: str,
        domain: str,
        snapshot: dict[str, Any],
        actor: str = "local_admin",
    ) -> dict[str, Any]:
        now = _now()
        snapshot_json = _json(snapshot)
        content_hash = _hash_text(snapshot_json)
        version = _version_name(source_type, content_hash, source_id=source_id)
        index_run_id = f"idx-{uuid4().hex}"
        with self._connect() as conn:
            try:
                conn.execute("BEGIN")
                version_cursor = conn.execute(
                    """
                    INSERT INTO knowledge_versions
                    (
                        shop_id, source_type, source_id, domain, version, content_hash, snapshot_json,
                        status, is_active, created_by, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_index', 0, ?, ?)
                    """,
                    (shop_id, source_type, source_id, domain, version, content_hash, snapshot_json, actor, now),
                )
                version_id = int(version_cursor.lastrowid)
                job_cursor = conn.execute(
                    """
                    INSERT INTO knowledge_index_jobs
                    (
                        shop_id, version_id, source_type, source_id, domain, version, status,
                        index_run_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (shop_id, version_id, source_type, source_id, domain, version, index_run_id, now),
                )
                job_id = int(job_cursor.lastrowid)
                conn.execute("UPDATE knowledge_versions SET index_job_id=? WHERE id=?", (job_id, version_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return {"version": self.get_version(version_id, conn=conn), "job": self.get_index_job(job_id, conn=conn)}

    def get_version(self, version_id: int, *, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        row = self._fetch_one("SELECT * FROM knowledge_versions WHERE id=?", (version_id,), conn=conn)
        if not row:
            raise KeyError(f"version_not_found:{version_id}")
        return row

    def list_versions(
        self,
        *,
        shop_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        domain: str | None = None,
        status: str | None = None,
        is_active: bool | None = None,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if shop_id:
            where.append("shop_id=?")
            params.append(shop_id)
        if source_type:
            where.append("source_type=?")
            params.append(source_type)
        if source_id:
            where.append("source_id=?")
            params.append(source_id)
        if domain:
            where.append("domain=?")
            params.append(domain)
        if status:
            where.append("status=?")
            params.append(status)
        if is_active is not None:
            where.append("is_active=?")
            params.append(1 if is_active else 0)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        return self._fetch_all(f"SELECT * FROM knowledge_versions {where_sql} ORDER BY created_at DESC, id DESC", tuple(params))

    def list_active_versions(self, shop_id: str | None = None) -> list[dict[str, Any]]:
        return self.list_versions(shop_id=shop_id, is_active=True)

    def activate_version(self, version_id: int) -> dict[str, Any]:
        now = _now()
        version = self.get_version(version_id)
        with self._connect() as conn:
            try:
                conn.execute("BEGIN")
                conn.execute(
                    """
                    UPDATE knowledge_versions
                    SET is_active=0, status=CASE WHEN status='active' THEN 'retired' ELSE status END, retired_at=?
                    WHERE shop_id=? AND source_type=? AND source_id=? AND domain=? AND is_active=1
                    """,
                    (now, version["shop_id"], version["source_type"], version["source_id"], version["domain"]),
                )
                conn.execute(
                    "UPDATE knowledge_versions SET is_active=1, status='active', activated_at=? WHERE id=?",
                    (now, version_id),
                )
                conn.commit()
                return self.get_version(version_id, conn=conn)
            except Exception:
                conn.rollback()
                raise

    def get_index_job(self, job_id: int, *, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        row = self._fetch_one("SELECT * FROM knowledge_index_jobs WHERE id=?", (job_id,), conn=conn)
        if not row:
            raise KeyError(f"index_job_not_found:{job_id}")
        return row

    def list_index_jobs(
        self,
        *,
        shop_id: str | None = None,
        status: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        version_id: int | None = None,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if shop_id:
            where.append("shop_id=?")
            params.append(shop_id)
        if status:
            where.append("status=?")
            params.append(status)
        if source_type:
            where.append("source_type=?")
            params.append(source_type)
        if source_id:
            where.append("source_id=?")
            params.append(source_id)
        if version_id is not None:
            where.append("version_id=?")
            params.append(version_id)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        return self._fetch_all(f"SELECT * FROM knowledge_index_jobs {where_sql} ORDER BY created_at DESC, id DESC", tuple(params))

    def mark_job_running(self, job_id: int) -> dict[str, Any]:
        now = _now()
        with self._connect() as conn:
            conn.execute("UPDATE knowledge_index_jobs SET status='running', started_at=? WHERE id=?", (now, job_id))
            conn.commit()
            return self.get_index_job(job_id, conn=conn)

    def mark_job_succeeded(self, job_id: int, *, chunk_count: int = 0, embedded_count: int = 0, indexed_count: int = 0) -> dict[str, Any]:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_index_jobs
                SET status='succeeded', chunk_count=?, embedded_count=?, indexed_count=?, finished_at=?, error_summary=NULL
                WHERE id=?
                """,
                (chunk_count, embedded_count, indexed_count, now, job_id),
            )
            job = self.get_index_job(job_id, conn=conn)
            conn.execute(
                "UPDATE knowledge_versions SET status='succeeded', indexed_at=?, error_summary=NULL WHERE id=?",
                (now, job["version_id"]),
            )
            conn.commit()
            return self.get_index_job(job_id, conn=conn)

    def mark_job_failed(self, job_id: int, error_summary: str) -> dict[str, Any]:
        now = _now()
        safe_error = error_summary[:500]
        with self._connect() as conn:
            conn.execute(
                "UPDATE knowledge_index_jobs SET status='failed', error_summary=?, finished_at=? WHERE id=?",
                (safe_error, now, job_id),
            )
            job = self.get_index_job(job_id, conn=conn)
            conn.execute(
                "UPDATE knowledge_versions SET status='failed', error_summary=? WHERE id=?",
                (safe_error, job["version_id"]),
            )
            conn.commit()
            return self.get_index_job(job_id, conn=conn)

    def retry_job(self, job_id: int) -> dict[str, Any]:
        now = _now()
        with self._connect() as conn:
            current = self.get_index_job(job_id, conn=conn)
            if current["status"] != "failed":
                raise ValueError(f"job_not_failed:{job_id}")
            conn.execute(
                """
                UPDATE knowledge_index_jobs
                SET status='retrying', retry_count=retry_count + 1, error_summary=NULL, started_at=NULL, finished_at=NULL
                WHERE id=?
                """,
                (job_id,),
            )
            job = self.get_index_job(job_id, conn=conn)
            conn.execute(
                "UPDATE knowledge_versions SET status='pending_index', error_summary=NULL WHERE id=?",
                (job["version_id"],),
            )
            conn.commit()
            return self.get_index_job(job_id, conn=conn)

    def run_fake_index_job(self, job_id: int) -> dict[str, dict[str, Any]]:
        now = _now()
        with self._connect() as conn:
            try:
                conn.execute("BEGIN")
                job = self.get_index_job(job_id, conn=conn)
                if job["status"] not in {"pending", "retrying"}:
                    raise ValueError(f"job_not_runnable:{job['status']}")
                version = self.get_version(job["version_id"], conn=conn)
                conn.execute("UPDATE knowledge_index_jobs SET status='running', started_at=? WHERE id=?", (now, job_id))
                try:
                    snapshot = json.loads(version["snapshot_json"])
                    if not isinstance(snapshot, dict) or not snapshot:
                        raise ValueError("empty_snapshot")
                    snapshot_text = _json(snapshot)
                    chunk_count = max(1, (len(snapshot_text) + 999) // 1000)
                except Exception as exc:
                    safe_error = f"fake_index_snapshot_error:{exc.__class__.__name__}"
                    conn.execute(
                        "UPDATE knowledge_index_jobs SET status='failed', error_summary=?, finished_at=? WHERE id=?",
                        (safe_error, now, job_id),
                    )
                    conn.execute(
                        "UPDATE knowledge_versions SET status='failed', error_summary=? WHERE id=?",
                        (safe_error, version["id"]),
                    )
                    conn.commit()
                    raise RuntimeError(safe_error) from exc
                conn.execute(
                    """
                    UPDATE knowledge_index_jobs
                    SET status='succeeded', chunk_count=?, embedded_count=?, indexed_count=?, error_summary=NULL, finished_at=?
                    WHERE id=?
                    """,
                    (chunk_count, chunk_count, chunk_count, now, job_id),
                )
                conn.execute(
                    """
                    UPDATE knowledge_versions
                    SET is_active=0, status=CASE WHEN status='active' THEN 'retired' ELSE status END, retired_at=?
                    WHERE shop_id=? AND source_type=? AND source_id=? AND domain=? AND is_active=1 AND id<>?
                    """,
                    (
                        now,
                        version["shop_id"],
                        version["source_type"],
                        version["source_id"],
                        version["domain"],
                        version["id"],
                    ),
                )
                conn.execute(
                    """
                    UPDATE knowledge_versions
                    SET status='active', is_active=1, indexed_at=?, activated_at=?, error_summary=NULL
                    WHERE id=?
                    """,
                    (now, now, version["id"]),
                )
                conn.commit()
                return {"version": self.get_version(version["id"], conn=conn), "index_job": self.get_index_job(job_id, conn=conn)}
            except ValueError:
                conn.rollback()
                raise
            except RuntimeError:
                raise
            except Exception:
                conn.rollback()
                raise

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _fetch_one(
        self,
        sql: str,
        params: tuple[Any, ...],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        if conn is not None:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None
        with self._connect() as local_conn:
            row = local_conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def _table_exists(self, table_name: str, *, conn: sqlite3.Connection | None = None) -> bool:
        sql = "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1"
        if conn is not None:
            return conn.execute(sql, (table_name,)).fetchone() is not None
        with self._connect() as local_conn:
            return local_conn.execute(sql, (table_name,)).fetchone() is not None


class KnowledgeCenterService:
    def __init__(self, db_path: str | Path | None = None, repository: KnowledgeCenterRepository | None = None) -> None:
        self.repository = repository or KnowledgeCenterRepository(db_path)

    def init_schema(self) -> None:
        self.repository.init_schema()

    def create_sop(self, shop_id: str, domain: str, title: str, content: str, actor: str = "local_admin") -> dict[str, Any]:
        return self.repository.create_sop(shop_id, domain, title, content, actor=actor)

    def update_sop(self, sop_id: int, *, title: str | None = None, content: str | None = None, actor: str = "local_admin") -> dict[str, Any]:
        return self.repository.update_sop(sop_id, title=title, content=content, actor=actor)

    def get_sop(self, sop_id: int) -> dict[str, Any]:
        return self.repository.get_sop(sop_id)

    def list_sop(self, **filters: Any) -> list[dict[str, Any]]:
        return self.repository.list_sop(**filters)

    def archive_sop(self, sop_id: int, actor: str = "local_admin") -> dict[str, Any]:
        return self.repository.archive_sop(sop_id, actor=actor)

    def get_override(self, shop_id: str, goods_id: str) -> dict[str, Any] | None:
        return self.repository.get_override(shop_id, goods_id)

    def upsert_override(self, shop_id: str, goods_id: str, **fields: Any) -> dict[str, Any]:
        return self.repository.upsert_override(shop_id, goods_id, **fields)

    def build_effective_product_knowledge(self, shop_id: str, goods_id: str) -> dict[str, Any]:
        raw = self.repository.get_product_raw(shop_id, goods_id)
        override = self.repository.get_override(shop_id, goods_id) or {}
        raw_payload = _product_raw_payload(raw)
        raw_detail = raw_payload["raw_detail_json"]
        specs = parse_json_list_or_text(raw_payload.get("specifications") or raw_detail.get("specifications") or raw_detail.get("sku_options"))
        fields = {
            "goods_name": _field(override.get("goods_name"), raw_payload.get("goods_name") or raw_detail.get("goods_name")),
            "price": {
                "value": str(raw_payload.get("price") or raw_detail.get("price") or ""),
                "source": "raw" if raw_payload.get("price") or raw_detail.get("price") else "missing",
            },
            "price_note": _field(override.get("price_note_override"), None),
            "specs": _field(override.get("specs_override"), specs),
            "usage": _field(override.get("usage_override"), pick_text(raw_detail, "usage", "usage_method", "how_to_use", "use_method")),
            "ingredients": _field(override.get("ingredients_override"), pick_text(raw_detail, "ingredients", "ingredient", "composition")),
            "warnings": _field(override.get("warnings_override"), pick_text(raw_detail, "warnings", "warning", "notice", "cautions")),
            "shelf_life": _field(override.get("shelf_life_override"), pick_text(raw_detail, "shelf_life", "expiry", "expiration")),
            "manual_notes": _field(override.get("manual_notes"), pick_text(raw_detail, "manual_notes", "notes")),
        }
        return {
            "source_type": "product",
            "shop_id": shop_id,
            "goods_id": goods_id,
            "goods_name": fields["goods_name"]["value"],
            "domain": "product_catalog",
            "fields": fields,
            "raw": raw_payload,
            "override": _override_payload(override, shop_id=shop_id, goods_id=goods_id),
        }

    def publish_sop(self, shop_id: str, sop_id: int, actor: str = "local_admin") -> dict[str, Any]:
        sop = self.repository.get_sop(sop_id)
        if sop["shop_id"] != shop_id:
            raise KeyError(f"sop_not_found:{shop_id}:{sop_id}")
        snapshot = {
            "source_type": "sop",
            "shop_id": shop_id,
            "sop_id": sop["id"],
            "domain": sop["domain"],
            "title": sop["title"],
            "content": sop["content"],
            "content_hash": sop["content_hash"],
        }
        return self.repository.create_version_and_job(
            shop_id=shop_id,
            source_type="sop",
            source_id=str(sop["id"]),
            domain=sop["domain"],
            snapshot=snapshot,
            actor=actor,
        )

    def publish_product(self, shop_id: str, goods_id: str, actor: str = "local_admin") -> dict[str, Any]:
        snapshot = self.build_effective_product_knowledge(shop_id, goods_id)
        result = self.repository.create_version_and_job(
            shop_id=shop_id,
            source_type="product",
            source_id=goods_id,
            domain="product_catalog",
            snapshot=snapshot,
            actor=actor,
        )
        return {"effective": snapshot, **result}

    def get_version(self, version_id: int) -> dict[str, Any]:
        return self.repository.get_version(version_id)

    def list_version_chunks(self, version_id: int, *, limit: int = 20) -> dict[str, Any]:
        version = self.repository.get_version(version_id)
        dsn = os.getenv("WEB_API_PGVECTOR_DSN") or os.getenv("AI_WORKFLOW_PGVECTOR_DSN") or ""
        if not dsn:
            return {
                "version_id": version_id,
                "source_type": version["source_type"],
                "source_id": version["source_id"],
                "domain": version["domain"],
                "version": version["version"],
                "chunks": [],
                "warning": "pgvector_not_configured",
            }
        try:
            import psycopg  # type: ignore
        except ImportError:
            return {
                "version_id": version_id,
                "source_type": version["source_type"],
                "source_id": version["source_id"],
                "domain": version["domain"],
                "version": version["version"],
                "chunks": [],
                "warning": "pgvector_driver_missing",
            }
        try:
            with psycopg.connect(dsn) as conn:
                rows = conn.execute(
                    """
                    SELECT chunk_id, shop_id, domain, source_type, source_id, version,
                           content, content_hash, metadata_json, created_at, index_run_id
                    FROM knowledge_chunks
                    WHERE metadata_json ->> 'version_id' = %s
                    ORDER BY updated_at DESC, created_at DESC, chunk_id
                    LIMIT %s
                    """,
                    (str(version_id), max(1, min(int(limit or 20), 100))),
                ).fetchall()
        except Exception as exc:  # pragma: no cover - exact deployment errors vary.
            return {
                "version_id": version_id,
                "source_type": version["source_type"],
                "source_id": version["source_id"],
                "domain": version["domain"],
                "version": version["version"],
                "chunks": [],
                "warning": _sanitize_error(f"pgvector_query_failed:{type(exc).__name__}"),
            }
        return {
            "version_id": version_id,
            "source_type": version["source_type"],
            "source_id": version["source_id"],
            "domain": version["domain"],
            "version": version["version"],
            "chunks": [_version_chunk_from_row(row) for row in rows],
            "warning": None,
        }

    def list_versions(self, **filters: Any) -> list[dict[str, Any]]:
        return self.repository.list_versions(**filters)

    def list_active_versions(self, shop_id: str | None = None) -> list[dict[str, Any]]:
        return self.repository.list_active_versions(shop_id)

    def activate_version(self, version_id: int) -> dict[str, Any]:
        return self.repository.activate_version(version_id)

    def get_index_job(self, job_id: int) -> dict[str, Any]:
        return self.repository.get_index_job(job_id)

    def list_index_jobs(self, **filters: Any) -> list[dict[str, Any]]:
        return self.repository.list_index_jobs(**filters)

    def mark_job_running(self, job_id: int) -> dict[str, Any]:
        return self.repository.mark_job_running(job_id)

    def mark_job_succeeded(self, job_id: int, *, chunk_count: int = 0, embedded_count: int = 0, indexed_count: int = 0) -> dict[str, Any]:
        return self.repository.mark_job_succeeded(job_id, chunk_count=chunk_count, embedded_count=embedded_count, indexed_count=indexed_count)

    def mark_job_failed(self, job_id: int, error_summary: str) -> dict[str, Any]:
        return self.repository.mark_job_failed(job_id, error_summary)

    def retry_job(self, job_id: int) -> dict[str, Any]:
        return self.repository.retry_job(job_id)

    def run_fake_index_job(self, job_id: int) -> dict[str, dict[str, Any]]:
        result = self.repository.run_fake_index_job(job_id)
        return {**result, "index_mode": "fake", "error_type": ""}

    def run_index_job(
        self,
        job_id: int,
        *,
        mode: str = "fake",
        embedding_provider: str = "fake",
        vector_store_provider: str = "none",
    ) -> dict[str, Any]:
        normalized_mode = str(mode or "fake").strip().lower()
        if normalized_mode != "real":
            return self.run_fake_index_job(job_id)
        return self.run_real_index_job(
            job_id,
            embedding_provider=embedding_provider,
            vector_store_provider=vector_store_provider,
        )

    def run_real_index_job(
        self,
        job_id: int,
        *,
        embedding_provider: str = "fake",
        vector_store_provider: str = "none",
        embedding_client: Any | None = None,
        vector_store: Any | None = None,
    ) -> dict[str, Any]:
        embedding_provider = str(embedding_provider or "fake").strip().lower()
        vector_store_provider = str(vector_store_provider or "none").strip().lower()
        job = self.repository.get_index_job(job_id)
        if job["status"] not in {"pending", "retrying"}:
            raise ValueError(f"job_not_runnable:{job['status']}")
        version = self.repository.get_version(job["version_id"])
        config_error = self._real_index_config_error(
            embedding_provider=embedding_provider,
            vector_store_provider=vector_store_provider,
            embedding_client=embedding_client,
            vector_store=vector_store,
        )
        if config_error:
            failed_job = self.repository.mark_job_failed(job_id, config_error)
            return {
                "version": self.repository.get_version(job["version_id"]),
                "index_job": failed_job,
                "index_mode": "real",
                "error_type": "config_missing",
            }
        try:
            self.repository.mark_job_running(job_id)
            current_job = self.repository.get_index_job(job_id)
            current_version = self.repository.get_version(current_job["version_id"])
            chunks = build_chunks_from_version_snapshot(current_version, current_job)
            if not chunks:
                raise KnowledgeIndexError("chunk_build_error:no_chunks")
            embedding_client = embedding_client or self._build_embedding_client(embedding_provider)
            vector_store = vector_store or self._build_vector_store(vector_store_provider)
            vectors = embedding_client.embed_batch([chunk.content for chunk in chunks])
            indexed_count = 0
            for chunk, embedding in zip(chunks, vectors, strict=True):
                vector_store.upsert(chunk, embedding.vector, embedding_model=embedding.model)
                indexed_count += 1
            succeeded_job = self.repository.mark_job_succeeded(
                job_id,
                chunk_count=len(chunks),
                embedded_count=len(vectors),
                indexed_count=indexed_count,
            )
            active_version = self.repository.activate_version(current_version["id"])
            return {
                "version": active_version,
                "index_job": succeeded_job,
                "index_mode": "real",
                "error_type": "",
            }
        except Exception as exc:  # noqa: BLE001 - keep index failures contained and observable.
            error_type = _classify_index_error(exc)
            safe_error = _sanitize_error(f"{error_type}:{exc}")
            failed_job = self.repository.mark_job_failed(job_id, safe_error)
            return {
                "version": self.repository.get_version(version["id"]),
                "index_job": failed_job,
                "index_mode": "real",
                "error_type": error_type,
            }

    def _real_index_config_error(
        self,
        *,
        embedding_provider: str,
        vector_store_provider: str,
        embedding_client: Any | None,
        vector_store: Any | None,
    ) -> str:
        missing: list[str] = []
        if embedding_client is None and embedding_provider == "ollama":
            for key in ("AI_WORKFLOW_OLLAMA_BASE_URL", "AI_WORKFLOW_EMBEDDING_MODEL"):
                if not os.getenv(key):
                    missing.append(key)
        if vector_store is None and vector_store_provider == "pgvector" and not os.getenv("AI_WORKFLOW_PGVECTOR_DSN"):
            missing.append("AI_WORKFLOW_PGVECTOR_DSN")
        return "config_missing:" + ",".join(missing) if missing else ""

    def _build_embedding_client(self, embedding_provider: str) -> Any:
        if embedding_provider == "ollama":
            return _OllamaEmbeddingClient(
                base_url=os.getenv("AI_WORKFLOW_OLLAMA_BASE_URL", ""),
                model=os.getenv("AI_WORKFLOW_EMBEDDING_MODEL", "bge-m3"),
            )
        return _FakeEmbeddingClient()

    def _build_vector_store(self, vector_store_provider: str) -> Any:
        if vector_store_provider == "pgvector":
            return _PgVectorUpsertStore(os.getenv("AI_WORKFLOW_PGVECTOR_DSN", ""))
        return _InMemoryVectorStore()


def _field(override_value: Any, raw_value: Any) -> dict[str, Any]:
    if _not_empty(override_value):
        return {"value": override_value, "source": "manual_override"}
    if _not_empty(raw_value):
        return {"value": raw_value, "source": "raw"}
    return {"value": "", "source": "missing"}


def _not_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_json(value: dict[str, Any]) -> str:
    return _hash_text(_json(value))


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def empty_product_override(shop_id: str, goods_id: str) -> dict[str, Any]:
    return {
        "id": None,
        "shop_id": shop_id,
        "goods_id": goods_id,
        "goods_name": "",
        "usage_override": "",
        "ingredients_override": "",
        "warnings_override": "",
        "shelf_life_override": "",
        "manual_notes": "",
        "specs_override": "",
        "price_note_override": "",
        "status": "draft",
        "content_hash": "",
        "created_by": "local_admin",
        "updated_by": "local_admin",
        "created_at": "",
        "updated_at": "",
    }


def _product_raw_payload(raw: dict[str, Any]) -> dict[str, Any]:
    raw_detail = parse_json_object(raw.get("raw_detail_json"))
    return {
        "shop_id": str(raw.get("shop_id") or ""),
        "goods_id": str(raw.get("goods_id") or ""),
        "goods_name": str(raw.get("goods_name") or raw_detail.get("goods_name") or ""),
        "price": str(raw.get("price") or raw_detail.get("price") or ""),
        "specifications": raw.get("specifications") or raw_detail.get("specifications") or raw_detail.get("sku_options") or "",
        "knowledge_status": str(raw.get("knowledge_status") or ""),
        "updated_at": str(raw.get("updated_at") or ""),
        "raw_detail_json": raw_detail,
    }


def _override_payload(override: dict[str, Any], *, shop_id: str, goods_id: str) -> dict[str, Any]:
    if not override:
        return empty_product_override(shop_id, goods_id)
    keys = [
        "id",
        "shop_id",
        "goods_id",
        "goods_name",
        "usage_override",
        "ingredients_override",
        "warnings_override",
        "shelf_life_override",
        "manual_notes",
        "specs_override",
        "price_note_override",
        "status",
        "content_hash",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    ]
    return {key: override.get(key) if override.get(key) is not None else "" for key in keys}


def _version_name(source_type: str, content_hash: str, *, source_id: str | None = None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    if source_type == "product" and source_id:
        return f"product-{source_id}-{stamp}"
    return f"{source_type}-{stamp}-{content_hash[:8]}"


class KnowledgeIndexError(RuntimeError):
    pass


def build_chunks_from_version_snapshot(version: dict[str, Any], job: dict[str, Any]) -> list["_KnowledgeChunk"]:
    try:
        snapshot = json.loads(version["snapshot_json"])
    except Exception as exc:  # noqa: BLE001
        raise KnowledgeIndexError("snapshot_missing:invalid_json") from exc
    if not isinstance(snapshot, dict) or not snapshot:
        raise KnowledgeIndexError("snapshot_missing:empty")
    content = _snapshot_to_chunk_content(snapshot, source_type=str(version["source_type"]))
    parts = _split_chunk_text(content)
    if not parts:
        raise KnowledgeIndexError("chunk_build_error:empty_content")
    chunks: list[_KnowledgeChunk] = []
    index_run_id = str(job.get("index_run_id") or "")
    namespace = "knowledge_center"
    for index, part in enumerate(parts, start=1):
        chunk_hash = _hash_text(part)
        chunk_id = _stable_chunk_id(
            shop_id=str(version["shop_id"]),
            version_id=int(version["id"]),
            source_type=str(version["source_type"]),
            source_id=str(version["source_id"]),
            domain=str(version["domain"]),
            chunk_hash=chunk_hash,
            index=index,
        )
        metadata = {
            "shop_id": version["shop_id"],
            "version_id": version["id"],
            "source_type": version["source_type"],
            "source_id": version["source_id"],
            "domain": version["domain"],
            "version": version["version"],
            "content_hash": version["content_hash"],
            "chunk_hash": chunk_hash,
            "index_run_id": index_run_id,
            "namespace": namespace,
            "created_by": version.get("created_by") or "local_admin",
            "is_test_data": False,
        }
        chunks.append(
            _KnowledgeChunk(
                chunk_id=chunk_id,
                shop_id=str(version["shop_id"]),
                domain=str(version["domain"]),
                source_type=str(version["source_type"]),
                source_id=str(version["source_id"]),
                title=_snapshot_title(snapshot, version),
                content=part,
                version=str(version["version"]),
                metadata=metadata,
                content_hash=chunk_hash,
            )
        )
    return chunks


def _snapshot_to_chunk_content(snapshot: dict[str, Any], *, source_type: str) -> str:
    if source_type == "sop":
        return "\n".join(
            [
                f"SOP: {snapshot.get('title') or ''}",
                f"Domain: {snapshot.get('domain') or ''}",
                f"Content: {snapshot.get('content') or ''}",
            ]
        ).strip()
    if source_type == "product":
        lines = [
            f"Product: {snapshot.get('goods_name') or snapshot.get('goods_id') or ''}",
            f"Goods ID: {snapshot.get('goods_id') or ''}",
            f"Domain: {snapshot.get('domain') or 'product_catalog'}",
        ]
        fields = snapshot.get("fields") or {}
        if isinstance(fields, dict):
            for field_name, field_value in fields.items():
                if not isinstance(field_value, dict):
                    continue
                value = field_value.get("value")
                source = field_value.get("source") or "missing"
                if _not_empty(value):
                    lines.append(f"{field_name} [{source}]: {value}")
                else:
                    lines.append(f"{field_name} [missing]: ")
        return "\n".join(lines).strip()
    return _json(snapshot)


def _split_chunk_text(content: str, *, max_chars: int = 1800) -> list[str]:
    text = str(content or "").strip()
    if not text:
        return []
    return [text[index : index + max_chars] for index in range(0, len(text), max_chars)]


def _stable_chunk_id(
    *,
    shop_id: str,
    version_id: int,
    source_type: str,
    source_id: str,
    domain: str,
    chunk_hash: str,
    index: int,
) -> str:
    seed = _hash_text("|".join([shop_id, str(version_id), source_type, source_id, domain, chunk_hash, str(index)]))
    return f"kc:{shop_id}:{version_id}:{seed[:32]}"


def _snapshot_title(snapshot: dict[str, Any], version: dict[str, Any]) -> str:
    if version["source_type"] == "sop":
        return str(snapshot.get("title") or f"SOP {version['source_id']}")
    return str(snapshot.get("goods_name") or snapshot.get("goods_id") or f"Product {version['source_id']}")


def _classify_index_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "config_missing" in text:
        return "config_missing"
    if "embedding" in text:
        return "embedding_error"
    if "pgvector" in text or "psycopg" in text or "connect" in text:
        return "pgvector_connection_error"
    if "upsert" in text:
        return "pgvector_upsert_error"
    if "snapshot_missing" in text or "snapshot" in text:
        return "snapshot_missing"
    if "chunk_build_error" in text or "chunk" in text:
        return "chunk_build_error"
    return "unexpected_error"


def _sanitize_error(value: str) -> str:
    text = str(value or "")
    dsn = os.getenv("AI_WORKFLOW_PGVECTOR_DSN", "")
    if dsn:
        text = text.replace(dsn, _mask_pg_dsn(dsn))
    text = re.sub(r"postgres(?:ql)?://[^\s]+", "<pg-dsn-redacted>", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)(password|token|api_key|authorization)=([^,\s]+)", r"\1=<redacted>", text)
    return text[:500]


def _version_chunk_from_row(row: Any) -> dict[str, Any]:
    metadata = dict(row[8] or {}) if isinstance(row[8], dict) else {}
    version_id = metadata.get("version_id")
    try:
        parsed_version_id = int(version_id) if version_id is not None else None
    except (TypeError, ValueError):
        parsed_version_id = None
    return {
        "chunk_id": str(row[0] or ""),
        "shop_id": str(row[1] or ""),
        "domain": str(row[2] or ""),
        "source_type": str(row[3] or ""),
        "source_id": str(row[4] or ""),
        "version": str(row[5] or ""),
        "content": str(row[6] or ""),
        "content_hash": str(row[7] or ""),
        "version_id": parsed_version_id,
        "chunk_hash": str(metadata.get("chunk_hash") or row[7] or ""),
        "index_run_id": str(metadata.get("index_run_id") or row[10] or ""),
        "metadata": metadata,
        "created_at": str(row[9] or ""),
    }


@dataclass(frozen=True)
class _KnowledgeChunk:
    chunk_id: str
    shop_id: str
    domain: str
    source_type: str
    source_id: str
    title: str
    content: str
    version: str
    metadata: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            object.__setattr__(self, "content_hash", _hash_text(self.content))

    def validate(self) -> list[str]:
        errors: list[str] = []
        for field_name in ("chunk_id", "shop_id", "domain", "source_type", "source_id", "version"):
            if not str(getattr(self, field_name) or "").strip():
                errors.append(f"{field_name} is required")
        return errors


@dataclass(frozen=True)
class _EmbeddingVector:
    model: str
    vector: list[float]


class _FakeEmbeddingClient:
    def __init__(self, *, dimension: int = 1024, model: str = "bge-m3") -> None:
        self.dimension = int(dimension)
        self.model = model

    def embed_batch(self, texts: list[str]) -> list[_EmbeddingVector]:
        return [self.embed(text) for text in texts]

    def embed(self, text: str) -> _EmbeddingVector:
        digest = _hash_text(text)
        values: list[float] = []
        for index in range(self.dimension):
            offset = (index * 2) % len(digest)
            raw = int(digest[offset : offset + 2], 16)
            values.append((raw / 127.5) - 1.0)
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return _EmbeddingVector(model=self.model, vector=[value / norm for value in values])


class _OllamaEmbeddingClient:
    def __init__(self, *, base_url: str, model: str, timeout: float = 15.0) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self.model = model
        self.timeout = float(timeout)

    def embed_batch(self, texts: list[str]) -> list[_EmbeddingVector]:
        return [self.embed(text) for text in texts]

    def embed(self, text: str) -> _EmbeddingVector:
        payload = json.dumps({"model": self.model, "prompt": text or ""}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310 - explicit opt-in.
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise KnowledgeIndexError(f"embedding_error:http_{exc.code}") from exc
        except urllib.error.URLError as exc:
            raise KnowledgeIndexError(f"embedding_error:{type(exc.reason).__name__}") from exc
        raw_vector = data.get("embedding") or data.get("embeddings")
        if isinstance(raw_vector, list) and raw_vector and isinstance(raw_vector[0], list):
            raw_vector = raw_vector[0]
        if not isinstance(raw_vector, list):
            raise KnowledgeIndexError("embedding_error:no_vector")
        return _EmbeddingVector(model=self.model, vector=[float(value) for value in raw_vector])


class _InMemoryVectorStore:
    def __init__(self) -> None:
        self._items: dict[str, tuple[_KnowledgeChunk, list[float], str]] = {}

    def upsert(self, chunk: _KnowledgeChunk, vector: list[float], *, embedding_model: str = "bge-m3") -> None:
        errors = chunk.validate()
        if errors:
            raise ValueError("; ".join(errors))
        self._items[chunk.chunk_id] = (chunk, list(vector), embedding_model)


class _PgVectorUpsertStore:
    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ValueError("pgvector DSN is required")
        try:
            import psycopg  # type: ignore
        except ImportError as exc:  # pragma: no cover - deployment dependency.
            raise KnowledgeIndexError("pgvector_connection_error:psycopg_missing") from exc
        self._psycopg = psycopg
        self._dsn = dsn

    def upsert(self, chunk: _KnowledgeChunk, vector: list[float], *, embedding_model: str = "bge-m3") -> None:
        errors = chunk.validate()
        if errors:
            raise ValueError("; ".join(errors))
        vector_literal = "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"
        try:
            with self._psycopg.connect(self._dsn) as conn:  # pragma: no cover - integration only.
                conn.execute(
                    """
                    INSERT INTO knowledge_chunks (
                        chunk_id, shop_id, domain, source_type, source_id, title, content,
                        content_hash, version, index_run_id, namespace, is_test_data, created_by, metadata_json,
                        embedding_model, embedding_dimension, embedding
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        content = EXCLUDED.content,
                        content_hash = EXCLUDED.content_hash,
                        version = EXCLUDED.version,
                        index_run_id = EXCLUDED.index_run_id,
                        namespace = EXCLUDED.namespace,
                        is_test_data = EXCLUDED.is_test_data,
                        created_by = EXCLUDED.created_by,
                        metadata_json = EXCLUDED.metadata_json,
                        embedding_model = EXCLUDED.embedding_model,
                        embedding_dimension = EXCLUDED.embedding_dimension,
                        embedding = EXCLUDED.embedding,
                        updated_at = now()
                    """,
                    (
                        chunk.chunk_id,
                        chunk.shop_id,
                        chunk.domain,
                        chunk.source_type,
                        chunk.source_id,
                        chunk.title,
                        chunk.content,
                        chunk.content_hash,
                        chunk.version,
                        chunk.metadata.get("index_run_id") or None,
                        chunk.metadata.get("namespace") or None,
                        bool(chunk.metadata.get("is_test_data", False)),
                        chunk.metadata.get("created_by") or None,
                        self._psycopg.types.json.Jsonb(chunk.metadata),
                        embedding_model,
                        len(vector),
                        vector_literal,
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeIndexError(f"pgvector_upsert_error:{type(exc).__name__}") from exc


def _mask_pg_dsn(dsn: str) -> str:
    if not dsn:
        return ""
    try:
        parsed = urlsplit(dsn)
    except ValueError:
        return "<invalid-dsn>"
    if not parsed.netloc:
        return dsn
    try:
        user = parsed.username or ""
        host = parsed.hostname or ""
        port_value = parsed.port
    except ValueError:
        return "<invalid-dsn>"
    port = f":{port_value}" if port_value else ""
    auth = f"{user}:***@" if user else ""
    return urlunsplit((parsed.scheme, f"{auth}{host}{port}", parsed.path, "", ""))
