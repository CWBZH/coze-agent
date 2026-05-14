"""
Redis 管理器 (V3.0 存根)

V2.0 遗留组件，保留为空存根以维持向后兼容。
实际功能已被 V3.0 的 SQLite + session 状态字段替代。
"""
import logging

logger = logging.getLogger("RedisManagerStub")


class _RedisStub:
    """Redis 操作的无操作存根 — 不实际连接 Redis，所有操作安全返回默认值。"""

    # 让 config_manager 的 `if redis_manager._client:` 短路
    _client = None

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

    # === 关键词 UI 兼容方法 ===
    def get_static_rules(self, shop_id) -> dict:
        return {}

    def set_static_rule(self, shop_id, keyword, reply) -> bool:
        return True

    def delete_static_rule(self, shop_id, keyword) -> bool:
        return True


redis_manager = _RedisStub()
