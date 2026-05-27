import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("temp/channel_shop.db")


@dataclass(frozen=True)
class ReadOnlyResult:
    rows: list[dict[str, Any]]
    warning: str | None = None


class ReadOnlySqlite:
    def __init__(self, db_path: str | Path | None = None) -> None:
        configured = db_path or os.getenv("WEB_API_SQLITE_DB_PATH") or DEFAULT_DB_PATH
        self.db_path = Path(configured)

    def query(self, sql: str, params: tuple[Any, ...] = (), required_tables: tuple[str, ...] = ()) -> ReadOnlyResult:
        if not self.db_path.exists():
            return ReadOnlyResult(rows=[], warning="db_missing")
        try:
            with self._connect() as conn:
                missing_table = self._first_missing_table(conn, required_tables)
                if missing_table:
                    return ReadOnlyResult(rows=[], warning=f"missing_table:{missing_table}")
                cursor = conn.execute(sql, params)
                rows = [dict(row) for row in cursor.fetchall()]
                return ReadOnlyResult(rows=rows)
        except sqlite3.Error as exc:
            return ReadOnlyResult(rows=[], warning=f"sqlite_error:{exc.__class__.__name__}")

    def count(self, sql: str, params: tuple[Any, ...] = (), required_tables: tuple[str, ...] = ()) -> tuple[int, str | None]:
        result = self.query(sql, params, required_tables)
        if result.warning:
            return 0, result.warning
        if not result.rows:
            return 0, None
        return int(next(iter(result.rows[0].values())) or 0), None

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self.db_path.resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _first_missing_table(conn: sqlite3.Connection, table_names: tuple[str, ...]) -> str | None:
        for table_name in table_names:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
                (table_name,),
            ).fetchone()
            if not exists:
                return table_name
        return None


def parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_json_list_or_text(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text = str(value)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [part.strip() for part in text.replace("\n", ";").split(";") if part.strip()]
    if isinstance(parsed, list):
        result: list[str] = []
        for item in parsed:
            if isinstance(item, dict):
                result.append(", ".join(f"{key}: {val}" for key, val in item.items()))
            elif str(item).strip():
                result.append(str(item).strip())
        return result
    if isinstance(parsed, dict):
        return [f"{key}: {val}" for key, val in parsed.items()]
    return [str(parsed)]


def pick_text(raw: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if value is not None and str(value).strip():
            if isinstance(value, (list, dict)):
                return json.dumps(value, ensure_ascii=False)
            return str(value).strip()
    return ""
