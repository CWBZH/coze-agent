"""Compatibility manager for legacy Redis-style APIs.

V3 uses SQLite as the durable store. The methods kept here are the small subset
still used by the message pipeline and PyQt UI.
"""
from __future__ import annotations

import json
import logging
from typing import Dict

logger = logging.getLogger("RedisManagerCompat")


class _RedisCompat:
    _client = None

    def _db(self):
        from database.db_manager import get_db_manager

        return get_db_manager()

    def _static_rules_key(self, shop_id) -> str:
        return f"shop:{shop_id}:static_rules"

    def _load_json_config(self, key: str) -> Dict:
        row = self._db().get_config(key)
        if not row:
            return {}
        try:
            value = row.get("config_value") or "{}"
            data = json.loads(value)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning("Failed to load config %s: %s", key, e)
            return {}

    def _save_json_config(self, key: str, value: Dict) -> bool:
        return self._db().set_config(key, json.dumps(value, ensure_ascii=False))

    # Human lock compatibility. V3 stores authoritative state in Conversation.status.
    def renew_human_lock(self, session_id: str, ttl: int = 240) -> bool:
        return True

    def get_lock_ttl(self, session_id: str) -> int:
        return 300

    def set_human_lock(self, session_id: str, ttl: int = 240) -> bool:
        return True

    def release_human_lock(self, session_id: str) -> bool:
        return True

    def has_human_lock(self, session_id: str) -> bool:
        return False

    def is_human_locked(self, session_id: str) -> bool:
        return False

    def acquire_inference_lock(self, session_id: str, ttl: int = 60) -> bool:
        return True

    def release_inference_lock(self, session_id: str) -> bool:
        return True

    def mark_ai_awakening(self, session_id: str, ttl: int = 30) -> bool:
        return True

    def is_ai_awakening(self, session_id: str) -> bool:
        return False

    def clear_ai_awakening(self, session_id: str) -> bool:
        return True

    def set_last_intent(self, session_id: str, intent, ttl: int = 300) -> bool:
        return True

    def get_last_intent(self, session_id: str):
        return None

    # Level-1 static rule compatibility.
    def get_static_rules(self, shop_id) -> dict:
        rules = self._load_json_config(self._static_rules_key(shop_id))
        if not rules and str(shop_id) != "default":
            rules = self._load_json_config(self._static_rules_key("default"))
        return {str(k): str(v) for k, v in rules.items() if str(k).strip() and str(v).strip()}

    def set_static_rule(self, shop_id, keyword, reply) -> bool:
        keyword = str(keyword or "").strip()
        reply = str(reply or "").strip()
        if not keyword or not reply:
            return False
        key = self._static_rules_key(shop_id)
        rules = self._load_json_config(key)
        rules[keyword] = reply
        return self._save_json_config(key, rules)

    def delete_static_rule(self, shop_id, keyword) -> bool:
        key = self._static_rules_key(shop_id)
        rules = self._load_json_config(key)
        rules.pop(str(keyword or "").strip(), None)
        return self._save_json_config(key, rules)

    def set_alert_cooldown(self, session_id: str, ttl: int = 60) -> bool:
        return True


redis_manager = _RedisCompat()
