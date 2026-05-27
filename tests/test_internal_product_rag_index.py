import json
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_product_rag_index.py"


def _run_raw(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


def _run(*args):
    completed = _run_raw(*args)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _product_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE shops (
            id INTEGER PRIMARY KEY,
            shop_id TEXT NOT NULL
        );
        CREATE TABLE product_knowledge (
            id INTEGER PRIMARY KEY,
            shop_id INTEGER NOT NULL,
            goods_id TEXT,
            goods_name TEXT,
            price_min TEXT,
            price_max TEXT,
            specifications TEXT,
            raw_detail_json TEXT,
            knowledge_status TEXT,
            manual_notes TEXT
        );
        INSERT INTO shops(id, shop_id) VALUES (1, 'synthetic-shop-1'), (2, 'other-shop');
        INSERT INTO product_knowledge(
            shop_id, goods_id, goods_name, price_min, price_max, specifications,
            raw_detail_json, knowledge_status, manual_notes
        ) VALUES (
            1, 'goods-1', 'Do Not Leak Product Name', '88', '99', '100ml',
            'RAW_DETAIL_JSON_SHOULD_NOT_LEAK', 'active', 'Use after cleaning'
        );
        INSERT INTO product_knowledge(shop_id, goods_id, goods_name, raw_detail_json)
        VALUES (2, 'goods-2', 'Other Shop Product', 'OTHER_RAW_DETAIL_SHOULD_NOT_LEAK');
        """
    )
    conn.commit()
    conn.close()


def test_missing_db_returns_missing(tmp_path):
    payload = _run(
        "--product-db-path",
        str(tmp_path / "missing.db"),
        "--from-product-db",
        "--shop-id",
        "synthetic-shop-1",
        "--dry-run",
        "--json-only",
    )

    assert payload["status"] == "missing"
    assert payload["source_record_count"] == 0


def test_missing_table_returns_missing_table(tmp_path):
    db_path = tmp_path / "empty.db"
    sqlite3.connect(db_path).close()

    payload = _run(
        "--product-db-path",
        str(db_path),
        "--from-product-db",
        "--shop-id",
        "synthetic-shop-1",
        "--dry-run",
        "--json-only",
    )

    assert payload["status"] == "missing_table"


def test_empty_shop_id_rejected(tmp_path):
    db_path = tmp_path / "products.db"
    _product_db(db_path)

    completed = _run_raw("--product-db-path", str(db_path), "--from-product-db", "--shop-id", "", "--json-only")
    assert completed.returncode != 0
    assert json.loads(completed.stdout)["error_type"] == "missing_shop_id"


def test_read_only_product_db_dry_run_is_sanitized(tmp_path):
    db_path = tmp_path / "products.db"
    _product_db(db_path)

    payload = _run(
        "--product-db-path",
        str(db_path),
        "--from-product-db",
        "--shop-id",
        "synthetic-shop-1",
        "--product-version",
        "real-product-v1",
        "--dry-run",
        "--json-only",
    )
    rendered = json.dumps(payload, ensure_ascii=False)

    assert payload["status"] == "dry_run"
    assert payload["source_record_count"] == 1
    assert payload["product_chunk_count"] == 1
    assert payload["product_version"] == "real-product-v1"
    assert payload["source_type"] == "product"
    assert payload["connects_pgvector"] is False
    assert payload["calls_ollama"] is False
    assert "RAW_DETAIL_JSON_SHOULD_NOT_LEAK" not in rendered
    assert "Do Not Leak Product Name" not in rendered


def test_fake_indexing_uses_in_memory_store(tmp_path):
    db_path = tmp_path / "products.db"
    _product_db(db_path)

    payload = _run(
        "--product-db-path",
        str(db_path),
        "--from-product-db",
        "--shop-id",
        "synthetic-shop-1",
        "--json-only",
    )

    assert payload["status"] == "ok"
    assert payload["embedded_count"] == payload["product_chunk_count"]
    assert payload["indexed_count"] == payload["product_chunk_count"]
    assert payload["connects_pgvector"] is False
    assert payload["calls_ollama"] is False


def test_real_mode_requires_safe_explicit_args(tmp_path):
    db_path = tmp_path / "products.db"
    _product_db(db_path)

    missing_dsn = _run_raw(
        "--product-db-path",
        str(db_path),
        "--from-product-db",
        "--shop-id",
        "synthetic-shop-1",
        "--real",
        "--embedding-provider",
        "ollama",
        "--json-only",
    )
    assert missing_dsn.returncode != 0
    assert json.loads(missing_dsn.stdout)["error_type"] == "missing_pg_dsn"

    fake_provider = _run_raw(
        "--product-db-path",
        str(db_path),
        "--from-product-db",
        "--shop-id",
        "synthetic-shop-1",
        "--real",
        "--pg-dsn",
        "postgresql://user:secret-password@127.0.0.1/db",
        "--embedding-provider",
        "fake",
        "--json-only",
    )
    assert fake_provider.returncode != 0
    assert json.loads(fake_provider.stdout)["error_type"] == "real_requires_ollama"
    assert "secret-password" not in fake_provider.stdout
