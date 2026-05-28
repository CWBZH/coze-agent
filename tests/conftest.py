import json
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def seed_default_web_api_sqlite() -> None:
    """Keep legacy Web API smoke tests deterministic without production fallbacks."""
    db_path = Path("temp/channel_shop.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY,
                channel_name TEXT
            );
            CREATE TABLE IF NOT EXISTS shops (
                id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                shop_id TEXT,
                shop_name TEXT
            );
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY,
                shop_id INTEGER,
                user_id TEXT,
                username TEXT,
                password TEXT,
                cookies TEXT,
                status INTEGER
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY,
                session_id TEXT,
                shop_id INTEGER,
                buyer_id TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS product_knowledge (
                id INTEGER PRIMARY KEY,
                shop_id INTEGER,
                goods_id TEXT,
                goods_name TEXT,
                price TEXT,
                price_min INTEGER,
                price_max INTEGER,
                specifications TEXT,
                raw_detail_json TEXT,
                knowledge_status TEXT,
                updated_at TEXT
            );
            """
        )
        shop_count = conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0]
        product_count = conn.execute("SELECT COUNT(*) FROM product_knowledge").fetchone()[0]
        if shop_count and product_count:
            return

        conn.execute("DELETE FROM product_knowledge")
        conn.execute("DELETE FROM conversations")
        conn.execute("DELETE FROM accounts")
        conn.execute("DELETE FROM shops")
        conn.execute("DELETE FROM channels")
        conn.execute("INSERT INTO channels (id, channel_name) VALUES (1, 'pinduoduo')")
        conn.execute(
            "INSERT INTO shops (id, channel_id, shop_id, shop_name) VALUES (1, 1, '323473738', '演示店铺')"
        )
        conn.execute(
            "INSERT INTO accounts (shop_id, user_id, username, password, cookies, status) VALUES (1, 'demo-user', 'demo', '', '', 1)"
        )
        conn.execute(
            "INSERT INTO conversations (session_id, shop_id, buyer_id, updated_at) VALUES ('demo-session', 1, 'buyer-demo', '2026-05-25 21:00')"
        )
        raw = {
            "title": "脖子身体懒人素颜霜",
            "usage": "洁面后取适量涂抹，轻轻推开。",
            "ingredients": "烟酰胺、保湿成分",
            "shelf_life": "三年",
            "warnings": "敏感肌先局部测试",
            "manual_notes": "价格以页面为准",
        }
        conn.execute(
            """
            INSERT INTO product_knowledge
            (shop_id, goods_id, goods_name, price, specifications, raw_detail_json, knowledge_status, updated_at)
            VALUES (1, '943269377110', '脖子身体懒人素颜霜', '19.70', ?, ?, 'active', '2026-05-25 21:00')
            """,
            (json.dumps(["一瓶"], ensure_ascii=False), json.dumps(raw, ensure_ascii=False)),
        )
