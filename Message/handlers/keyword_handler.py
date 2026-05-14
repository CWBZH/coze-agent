"""关键词预检处理器 — SQLite 本地匹配"""
from typing import Optional, Dict
from database.models import Keyword
from utils.logger_loguru import get_logger

logger = get_logger("KeywordHandler")


class KeywordHandler:
    def __init__(self, db_manager):
        self.db = db_manager

    def check(self, shop_db_id: int, text: str) -> Optional[Dict]:
        with self.db.session_scope() as session:
            keywords = session.query(Keyword).filter(
                Keyword.shop_id == shop_db_id,
                Keyword.enabled == True
            ).all()
        for kw in keywords:
            if kw.keyword in text:
                logger.info(f"关键词命中: '{kw.keyword}' action={kw.action}")
                return {
                    "matched": True,
                    "keyword": kw.keyword,
                    "action": kw.action,
                    "reply_text": kw.reply_text or ""
                }
        return {"matched": False}
