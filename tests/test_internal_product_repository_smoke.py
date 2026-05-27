import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, Channel, ProductKnowledge, Shop
from scripts.acceptance.internal_product_repository_smoke import run_smoke


SCRIPT = Path("scripts/acceptance/internal_product_repository_smoke.py")
SHOP_ID = "shop-smoke-private"
PRODUCT_TITLE = "玫瑰精华水"
FULL_DETAIL = "完整商品详情不应出现在输出中"
BUYER_CONTENT = "买家完整咨询内容不应出现在输出中"
PRIVATE_MARKER = "private-marker-value"


def _create_db(path: Path, *, with_data: bool = True) -> None:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    try:
        channel = Channel(channel_name="pinduoduo", description="smoke")
        shop = Shop(channel=channel, shop_id=SHOP_ID, shop_name="Smoke Shop")
        session.add_all([channel, shop])
        if with_data:
            raw_detail = {
                "manual_attributes": {
                    "usage_method": "早晚洁面后使用",
                    "ingredients": "玫瑰提取物",
                    "manual_notes": FULL_DETAIL,
                },
                "private_marker": PRIVATE_MARKER,
            }
            session.add(
                ProductKnowledge(
                    shop=shop,
                    goods_id="rose-water",
                    goods_name=PRODUCT_TITLE,
                    price="99元",
                    specifications="100ml",
                    raw_detail_json=json.dumps(raw_detail, ensure_ascii=False),
                )
            )
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _product_count(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM product_knowledge").fetchone()[0])


def _run_script(*args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_smoke_reads_real_sqlite_product_records(tmp_path):
    db_path = tmp_path / "channel_shop.db"
    _create_db(db_path)

    summary = run_smoke(db_path=db_path, shop_id=SHOP_ID, query=f"{PRODUCT_TITLE} 成分")

    assert summary["status"] == "ok"
    assert summary["record_count"] == 1
    assert summary["hit_count"] == 1
    assert summary["shop_id_hash"]
    assert summary["top_hit_title_hash"]
    assert summary["query"].startswith("sha256:")


def test_smoke_connection_is_read_only_and_does_not_modify_data(tmp_path):
    db_path = tmp_path / "channel_shop.db"
    _create_db(db_path)

    before = _product_count(db_path)
    summary = run_smoke(db_path=db_path, shop_id=SHOP_ID, query=f"{PRODUCT_TITLE} 用法")
    after = _product_count(db_path)

    assert summary["status"] == "ok"
    assert before == after == 1


def test_smoke_reports_missing_db(tmp_path):
    summary = run_smoke(db_path=tmp_path / "missing.db", shop_id=SHOP_ID, query="anything")

    assert summary["status"] == "missing"
    assert summary["record_count"] == 0
    assert summary["hit_count"] == 0


def test_smoke_reports_missing_table(tmp_path):
    db_path = tmp_path / "missing_table.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE shops (id INTEGER PRIMARY KEY)")

    summary = run_smoke(db_path=db_path, shop_id=SHOP_ID, query="anything")

    assert summary["status"] == "missing_table"
    assert summary["record_count"] == 0
    assert summary["hit_count"] == 0


def test_smoke_reports_empty_table_for_shop_without_products(tmp_path):
    db_path = tmp_path / "empty.db"
    _create_db(db_path, with_data=False)

    summary = run_smoke(db_path=db_path, shop_id=SHOP_ID, query=f"{PRODUCT_TITLE} 成分")

    assert summary["status"] == "empty"
    assert summary["record_count"] == 0
    assert summary["hit_count"] == 0


def test_cli_json_output_does_not_include_full_details_or_buyer_content(tmp_path):
    db_path = tmp_path / "channel_shop.db"
    _create_db(db_path)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--db-path",
            str(db_path),
            "--shop-id",
            SHOP_ID,
            "--query",
            f"{PRODUCT_TITLE} {BUYER_CONTENT}",
            "--json-only",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(result.stdout)

    assert summary["status"] == "ok"
    assert PRODUCT_TITLE not in result.stdout
    assert FULL_DETAIL not in result.stdout
    assert BUYER_CONTENT not in result.stdout
    assert PRIVATE_MARKER not in result.stdout
    assert SHOP_ID not in result.stdout


def test_cli_defaults_to_db_path_env_then_temp_fallback(tmp_path, monkeypatch):
    db_path = tmp_path / "env.db"
    _create_db(db_path)
    monkeypatch.setenv("DB_PATH", str(db_path))

    summary = _run_script("--shop-id", SHOP_ID, "--query", f"{PRODUCT_TITLE} 成分", "--json-only")

    assert summary["status"] == "ok"
    assert summary["db_path"] == str(db_path.resolve())
