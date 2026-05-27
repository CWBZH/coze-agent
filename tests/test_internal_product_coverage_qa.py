import json
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_product_coverage_qa.py"


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
        CREATE TABLE shops (id INTEGER PRIMARY KEY, shop_id TEXT NOT NULL);
        CREATE TABLE product_knowledge (
            id INTEGER PRIMARY KEY,
            shop_id INTEGER NOT NULL,
            goods_id TEXT,
            goods_name TEXT,
            price TEXT,
            specifications TEXT,
            usage_method TEXT,
            ingredients TEXT,
            shelf_life TEXT,
            warnings TEXT,
            manual_notes TEXT,
            raw_detail_json TEXT
        );
        INSERT INTO shops(id, shop_id) VALUES (1, 'synthetic-shop-1');
        INSERT INTO product_knowledge(
            shop_id, goods_id, goods_name, price, specifications, usage_method,
            ingredients, shelf_life, warnings, manual_notes, raw_detail_json
        ) VALUES (
            1, 'goods-1', 'Private Product Name Should Not Leak', '99', '100ml',
            'Use after cleaning', 'Private ingredients', '24 months',
            'Patch test first', 'Private notes', 'RAW_DETAIL_JSON_SHOULD_NOT_LEAK'
        );
        """
    )
    conn.commit()
    conn.close()


def test_fake_product_coverage_qa_passes_without_external_services():
    payload = _run("--json-only")

    assert payload["status"] == "passed"
    assert payload["total"] > 0
    assert payload["hit_rate"] >= 0.9
    assert payload["field_coverage_rate"] >= 0.8
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False
    assert payload["calls_llm"] is False
    assert payload["no_send"] is True


def test_missing_db_is_unclear_not_crash(tmp_path):
    payload = _run(
        "--product-db-path",
        str(tmp_path / "missing.db"),
        "--from-product-db",
        "--shop-id",
        "synthetic-shop-1",
        "--json-only",
    )

    assert payload["status"] == "unclear"
    assert payload["error_type"] == "missing_db"


def test_empty_shop_id_rejected():
    completed = _run_raw("--shop-id", "", "--json-only")
    assert completed.returncode != 0
    assert json.loads(completed.stdout)["error_type"] == "missing_shop_id"


def test_read_only_db_cases_are_sanitized(tmp_path):
    db_path = tmp_path / "products.db"
    _product_db(db_path)

    payload = _run(
        "--product-db-path",
        str(db_path),
        "--from-product-db",
        "--shop-id",
        "synthetic-shop-1",
        "--limit",
        "5",
        "--json-only",
    )
    rendered = json.dumps(payload, ensure_ascii=False)

    assert payload["status"] == "passed"
    assert payload["source_record_count"] == 1
    assert "Private Product Name Should Not Leak" not in rendered
    assert "RAW_DETAIL_JSON_SHOULD_NOT_LEAK" not in rendered
    assert "Private ingredients" not in rendered


def test_real_rag_missing_args_fails_without_external_calls():
    completed = _run_raw("--real-rag", "--json-only")

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "error"
    assert "missing_pg_dsn" in payload["error_type"]
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_threshold_failure_returns_nonzero():
    completed = _run_raw("--expected-min-hit-rate", "1.1", "--json-only")

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
