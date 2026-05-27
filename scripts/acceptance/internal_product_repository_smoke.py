"""Read-only smoke check for the internal SQLite product repository."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import Session.session_manager  # noqa: F401
from Message.workflow.knowledge import ProductKnowledgeRetriever
from Message.workflow.knowledge_repository import ProductKnowledgeRepository


REQUIRED_TABLES = {"shops", "product_knowledge"}
DEFAULT_QUERY = "商品规格 用法 成分"


def _hash_text(value: Any) -> str:
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _masked_text(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    return f"sha256:{_hash_text(text)};len:{len(text)}"


def _default_db_path() -> Path:
    configured = os.getenv("DB_PATH")
    if configured and configured.strip():
        return Path(configured.strip())
    return Path("temp") / "channel_shop.db"


def _sqlite_uri(db_path: Path) -> str:
    absolute = db_path.resolve()
    return f"file:{quote(absolute.as_posix(), safe='/:')}?mode=ro"


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(_sqlite_uri(db_path), uri=True)


def _table_names(db_path: Path) -> set[str]:
    with _connect_readonly(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


def _session_provider(db_path: Path):
    def creator():
        return sqlite3.connect(_sqlite_uri(db_path), uri=True, check_same_thread=False)

    engine = create_engine("sqlite://", creator=creator)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    def provider():
        return SessionLocal()

    return provider, engine


def run_smoke(*, db_path: Path, shop_id: str, query: str) -> dict[str, Any]:
    resolved_db_path = db_path.resolve()
    summary: dict[str, Any] = {
        "db_path": str(resolved_db_path),
        "shop_id_hash": _hash_text(shop_id),
        "record_count": 0,
        "query": _masked_text(query),
        "hit_count": 0,
        "top_hit_title_hash": "",
        "status": "missing",
    }

    if not resolved_db_path.exists():
        return summary

    try:
        tables = _table_names(resolved_db_path)
    except sqlite3.Error:
        summary["status"] = "missing_table"
        return summary

    if not REQUIRED_TABLES.issubset(tables):
        summary["status"] = "missing_table"
        return summary

    provider, engine = _session_provider(resolved_db_path)
    try:
        repository = ProductKnowledgeRepository(session_provider=provider, enable_cache=False)
        records = repository.load_records(shop_id=shop_id)
        summary["record_count"] = len(records)
        if not records:
            summary["status"] = "empty"
            return summary

        retriever = ProductKnowledgeRetriever(records)
        hits = retriever.search(shop_id=shop_id, domain="product_basic", query=query)
        summary["hit_count"] = len(hits)
        if hits:
            summary["top_hit_title_hash"] = _hash_text(hits[0].title)
        summary["status"] = "ok"
        return summary
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a read-only SQLite smoke check against internal product knowledge."
    )
    parser.add_argument("--db-path", default=None, help="SQLite DB path. Defaults to DB_PATH or temp/channel_shop.db.")
    parser.add_argument("--shop-id", default="", help="Platform shop id to inspect.")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="Search query used for retriever smoke.")
    parser.add_argument("--json-only", action="store_true", help="Print only the JSON summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    summary = run_smoke(db_path=db_path, shop_id=args.shop_id, query=args.query)
    payload = json.dumps(summary, ensure_ascii=False, sort_keys=True)

    if not args.json_only:
        print("internal_product_repository_smoke")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
