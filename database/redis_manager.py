"""
Redis 管理器模块

实现基于 Redis 的人工静默锁机制，防止 AI 和人工客服抢话。

核心功能：
- set_human_lock: 设置人工接管锁（默认 240 秒）
- is_human_locked: 检查用户是否被人工接管
- renew_human_lock: 续期人工锁（人工客服发消息时触发）

V2.0 战役七：上线预备重构
- 抽离硬编码 TTL 到 core.config
- 实施 Fail-Safe 熔断保护（Redis 宕机时静默 AI）
"""
from __future__ import annotations

from typing import Optional
from utils.logger_loguru import get_logger

# 导入集中式配置
from core.config import (
    HUMAN_LOCK_TTL,
    INFERENCE_LOCK_TTL,
    INTENT_CACHE_TTL,
    ALERT_COOLDOWN_TTL,
    AI_AWAKENING_TTL,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_PASSWORD,
    REDIS_DB,
)
from core.constants import REDIS_FAILSAFE_ALERT, INFERENCE_LOCK_WARNING

logger = get_logger("RedisManager")

# Redis 配置（从集中式配置导入）
REDIS_CONFIG = {
    "host": REDIS_HOST,
    "port": REDIS_PORT,
    "password": REDIS_PASSWORD,
    "db": REDIS_DB,
    "decode_responses": True,
}

# 锁的 key 前缀
HUMAN_LOCK_PREFIX = "human_lock:"
INTENT_CACHE_PREFIX = "intent_cache:"
INFERENCE_LOCK_PREFIX = "inference_lock:"
AI_AWAKENING_PREFIX = "ai_awakening:"  # AI 苏醒标记（刚从人工接管转回）
ALERT_COOLDOWN_PREFIX = "alert_cooldown:"  # 警报冷却防抖


class RedisManager:
    """
    Redis 管理器（单例模式）

    用于管理人工静默锁，防止 AI 和人工客服同时回复。
    """

    _instance: Optional['RedisManager'] = None
    _client = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._client is not None:
            return

        self._connect()

    def _connect(self):
        """连接 Redis"""
        try:
            import redis
            self._client = redis.Redis(
                host=REDIS_CONFIG["host"],
                port=REDIS_CONFIG["port"],
                password=REDIS_CONFIG["password"],
                db=REDIS_CONFIG["db"],
                decode_responses=REDIS_CONFIG["decode_responses"],
            )
            # 测试连接
            self._client.ping()
            logger.info(f"Redis 连接成功: {REDIS_CONFIG['host']}:{REDIS_CONFIG['port']}")
        except ImportError:
            logger.error("redis 模块未安装，请运行: pip install redis")
            self._client = None
        except Exception as e:
            logger.error(f"Redis 连接失败: {e}")
            self._client = None

    def _get_lock_key(self, user_id: str) -> str:
        """获取锁的 Redis key"""
        return f"{HUMAN_LOCK_PREFIX}{user_id}"

    def set_human_lock(self, user_id: str, ttl: int = None) -> bool:
        """
        设置人工接管锁

        Args:
            user_id: 用户ID（通常是 session_id 或 from_uid）
            ttl: 锁的有效期（秒），默认使用配置 HUMAN_LOCK_TTL

        Returns:
            是否设置成功
        """
        if ttl is None:
            ttl = HUMAN_LOCK_TTL

        if self._client is None:
            logger.warning("Redis 未连接，无法设置人工锁")
            return False

        try:
            key = self._get_lock_key(user_id)
            result = self._client.setex(key, ttl, "1")
            logger.info(f"人工锁已设置: user_id={user_id}, ttl={ttl}s")
            return bool(result)
        except Exception as e:
            logger.error(f"设置人工锁失败: {e}")
            return False

    def is_human_locked(self, user_id: str) -> bool:
        """
        检查用户是否被人工接管（Fail-Safe 熔断保护）

        ⚠️ Fail-Safe 机制：
        - 当 Redis 连接失败时，返回 True（静默 AI）
        - 防止 AI 和人工客服同时抢话
        - 宁可让 AI 误静默，不让用户困惑

        Args:
            user_id: 用户ID

        Returns:
            True 表示被人工接管，AI 应静默
        """
        if self._client is None:
            # ✅ Fail-Safe: Redis 连接丢失时，强行静默 AI 以防抢话
            logger.critical(REDIS_FAILSAFE_ALERT)
            return True

        try:
            key = self._get_lock_key(user_id)
            return bool(self._client.exists(key))
        except Exception as e:
            # ✅ Fail-Safe: 异常时也返回 True，确保 AI 静默
            logger.critical(f"{REDIS_FAILSAFE_ALERT} 异常详情: {e}")
            return True

    def renew_human_lock(self, user_id: str, ttl: int = None) -> bool:
        """
        续期人工锁（仅当锁存在时）

        当人工客服发送消息时调用，重置锁的过期时间。

        Args:
            user_id: 用户ID
            ttl: 新的有效期（秒），默认使用配置 HUMAN_LOCK_TTL

        Returns:
            True 表示续期成功，False 表示锁不存在或失败
        """
        if ttl is None:
            ttl = HUMAN_LOCK_TTL

        if self._client is None:
            return False

        try:
            key = self._get_lock_key(user_id)
            # 只有锁存在时才续期
            if self._client.exists(key):
                self._client.expire(key, ttl)
                logger.debug(f"人工锁已续期: user_id={user_id}, ttl={ttl}s")
                return True
            return False
        except Exception as e:
            logger.error(f"续期人工锁失败: {e}")
            return False

    def release_human_lock(self, user_id: str) -> bool:
        """
        释放人工锁

        当人工客服主动结束会话或超时后调用。
        同时设置 AI 苏醒标记，提示后续首条回复需要自然接话。

        Args:
            user_id: 用户ID

        Returns:
            是否释放成功
        """
        if self._client is None:
            return False

        try:
            key = self._get_lock_key(user_id)
            self._client.delete(key)
            # 设置 AI 苏醒标记（30秒内首条回复需要注入苏醒指令）
            self.mark_ai_awakening(user_id, ttl=30)
            logger.info(f"人工锁已释放: user_id={user_id}, AI 苏醒标记已设置")
            return True
        except Exception as e:
            logger.error(f"释放人工锁失败: {e}")
            return False

    def get_lock_ttl(self, user_id: str) -> int:
        """
        获取锁的剩余有效期

        Args:
            user_id: 用户ID

        Returns:
            剩余秒数，-1 表示锁不存在，-2 表示出错
        """
        if self._client is None:
            return -2

        try:
            key = self._get_lock_key(user_id)
            ttl = self._client.ttl(key)
            return ttl
        except Exception as e:
            logger.error(f"获取锁 TTL 失败: {e}")
            return -2

    def health_check(self) -> bool:
        """
        健康检查

        Returns:
            Redis 是否可用
        """
        if self._client is None:
            return False

        try:
            return self._client.ping()
        except Exception:
            return False

    # =========================================================================
    # 意图缓存功能（Context Memory）
    # =========================================================================

    def _get_intent_key(self, session_id: str) -> str:
        """获取意图缓存的 Redis key"""
        return f"{INTENT_CACHE_PREFIX}{session_id}"

    def set_last_intent(self, session_id: str, intent: str, ttl: int = None) -> bool:
        """
        设置意图缓存（10分钟生命周期）

        用于极短句（<=5字符）的意图继承，避免重复调用 LLM 分类。

        Args:
            session_id: 会话ID
            intent: 意图类型（如 pre_sale, after_sales, logistics 等）
            ttl: 缓存有效期（秒），默认使用配置 INTENT_CACHE_TTL

        Returns:
            是否设置成功
        """
        if ttl is None:
            ttl = INTENT_CACHE_TTL

        if self._client is None:
            logger.warning("Redis 未连接，无法设置意图缓存")
            return False

        try:
            key = self._get_intent_key(session_id)
            result = self._client.setex(key, ttl, intent)
            logger.debug(f"意图缓存已设置: session_id={session_id}, intent={intent}, ttl={ttl}s")
            return bool(result)
        except Exception as e:
            logger.error(f"设置意图缓存失败: {e}")
            return False

    def get_last_intent(self, session_id: str) -> Optional[str]:
        """
        获取上一次的意图缓存

        用于极短句（<=5字符）的意图继承。

        Args:
            session_id: 会话ID

        Returns:
            意图类型字符串，如果不存在则返回 None
        """
        if self._client is None:
            return None

        try:
            key = self._get_intent_key(session_id)
            intent = self._client.get(key)
            if intent:
                logger.debug(f"意图缓存命中: session_id={session_id}, intent={intent}")
            return intent
        except Exception as e:
            logger.error(f"获取意图缓存失败: {e}")
            return None

    # =========================================================================
    # AI 推理互斥锁（防止并发推理压垮显存）
    # =========================================================================

    def _get_inference_lock_key(self, session_id: str) -> str:
        """获取推理锁的 Redis key"""
        return f"{INFERENCE_LOCK_PREFIX}{session_id}"

    # Lua 脚本：原子性获取推理锁
    # 返回 1 表示获取成功，0 表示锁已存在
    _LUA_ACQUIRE_INFERENCE_LOCK = """
    local current = redis.call('exists', KEYS[1])
    if current == 0 then
        redis.call('setex', KEYS[1], ARGV[1], '1')
        return 1
    else
        return 0
    end
    """

    def acquire_inference_lock(self, session_id: str, ttl: int = None) -> bool:
        """
        获取 AI 推理互斥锁（Lua 脚本保证绝对原子性 + Fail-Safe 保护）

        使用 Redis Lua 脚本实现原子性分布式锁。
        Lua 脚本在 Redis 中单线程执行，不存在竞态条件。

        ⚠️ Fail-Safe 机制：
        - 当 Redis 连接失败时，返回 False（阻止推理）
        - 防止并发请求压垮本地 GPU 显存
        - 宁可丢弃请求，不让系统崩溃

        Args:
            session_id: 会话ID
            ttl: 锁的有效期（秒），默认使用配置 INFERENCE_LOCK_TTL

        Returns:
            True 表示获取锁成功，可以开始推理
            False 表示锁已存在或 Redis 故障，需要等待或丢弃消息
        """
        if ttl is None:
            ttl = INFERENCE_LOCK_TTL

        if self._client is None:
            # ✅ Fail-Safe: Redis 连接丢失时，阻止推理请求
            logger.warning(INFERENCE_LOCK_WARNING)
            return False

        try:
            key = self._get_inference_lock_key(session_id)

            # 使用 Lua 脚本保证绝对原子性
            # eval(script, numkeys, key, ttl)
            result = self._client.eval(
                self._LUA_ACQUIRE_INFERENCE_LOCK,
                1,  # numkeys
                key,  # KEYS[1]
                ttl   # ARGV[1]
            )

            if result == 1:
                logger.debug(f"推理锁获取成功: session_id={session_id}, ttl={ttl}s")
                return True
            else:
                logger.debug(f"推理锁获取失败: session_id={session_id}, 锁已存在")
                return False

        except Exception as e:
            # ✅ Fail-Safe: 异常时阻止推理
            logger.error(f"获取推理锁失败: {e}")
            return False

    def release_inference_lock(self, session_id: str) -> None:
        """
        释放 AI 推理互斥锁

        推理完成后必须调用此方法释放锁，否则需要等待 TTL 自动过期。

        Args:
            session_id: 会话ID
        """
        if self._client is None:
            return

        try:
            key = self._get_inference_lock_key(session_id)
            self._client.delete(key)
            logger.debug(f"推理锁已释放: session_id={session_id}")
        except Exception as e:
            logger.error(f"释放推理锁失败: {e}")

    # =========================================================================
    # AI 苏醒状态标记（刚从人工接管转回 AI）
    # =========================================================================

    def _get_awakening_key(self, session_id: str) -> str:
        """获取 AI 苏醒标记的 Redis key"""
        return f"{AI_AWAKENING_PREFIX}{session_id}"

    def mark_ai_awakening(self, session_id: str, ttl: int = None) -> bool:
        """
        标记 AI 刚从人工接管转回（苏醒状态）

        当人工锁过期或被释放时调用，标记接下来的首条回复需要注入苏醒指令。

        Args:
            session_id: 会话ID
            ttl: 标记有效期（秒），默认使用配置 AI_AWAKENING_TTL

        Returns:
            是否标记成功
        """
        if ttl is None:
            ttl = AI_AWAKENING_TTL

        if self._client is None:
            return False

        try:
            key = self._get_awakening_key(session_id)
            result = self._client.setex(key, ttl, "1")
            logger.debug(f"AI 苏醒标记已设置: session_id={session_id}, ttl={ttl}s")
            return bool(result)
        except Exception as e:
            logger.error(f"设置 AI 苏醒标记失败: {e}")
            return False

    def is_ai_awakening(self, session_id: str) -> bool:
        """
        检查是否处于 AI 苏醒状态（刚从人工接管转回）

        Args:
            session_id: 会话ID

        Returns:
            True 表示需要注入苏醒指令
        """
        if self._client is None:
            return False

        try:
            key = self._get_awakening_key(session_id)
            exists = bool(self._client.exists(key))
            if exists:
                # 检查后自动清除（只对首条回复生效）
                self._client.delete(key)
                logger.debug(f"AI 苏醒状态检测并清除: session_id={session_id}")
            return exists
        except Exception as e:
            logger.error(f"检查 AI 苏醒状态失败: {e}")
            return False

    def clear_ai_awakening(self, session_id: str) -> bool:
        """
        手动清除 AI 苏醒标记

        Args:
            session_id: 会话ID

        Returns:
            是否成功清除
        """
        if self._client is None:
            return False

        try:
            key = self._get_awakening_key(session_id)
            self._client.delete(key)
            logger.debug(f"AI 苏醒标记已清除: session_id={session_id}")
            return True
        except Exception as e:
            logger.error(f"清除 AI 苏醒标记失败: {e}")
            return False

    # =========================================================================
    # 警报冷却防抖（防止弹窗轰炸）
    # =========================================================================

    def _get_alert_cooldown_key(self, user_id: str) -> str:
        """获取警报冷却的 Redis key"""
        return f"{ALERT_COOLDOWN_PREFIX}{user_id}"

    def set_alert_cooldown(self, user_id: str, ttl: int = None) -> bool:
        """
        设置警报冷却标记（防抖机制）

        使用 Redis SETNX 原子操作实现冷却检测。
        如果 key 已存在，返回 False（说明在冷却中）。
        如果不存在，设置成功并返回 True（可以发送警报）。

        解决内存泄漏问题：
        - 本地字典 _last_alert_times 在长期运行中会无限增长
        - Redis 的 TTL 自动过期机制确保内存可控

        Args:
            user_id: 用户 ID
            ttl: 冷却时间（秒），默认使用配置 ALERT_COOLDOWN_TTL

        Returns:
            True 表示可以发送警报（设置成功）
            False 表示在冷却中（跳过警报）
        """
        if ttl is None:
            ttl = ALERT_COOLDOWN_TTL

        if self._client is None:
            logger.warning("Redis 未连接，跳过警报冷却检查")
            return True  # Redis 不可用时，允许发送警报

        try:
            key = self._get_alert_cooldown_key(user_id)

            # 原子操作：SET key value EX ttl NX
            # 仅当 key 不存在时才设置，并添加过期时间
            acquired = self._client.set(key, "1", ex=ttl, nx=True)

            if acquired:
                logger.debug(f"警报冷却标记设置成功: user_id={user_id}, ttl={ttl}s")
                return True
            else:
                logger.debug(f"警报冷却中: user_id={user_id}")
                return False

        except Exception as e:
            logger.error(f"设置警报冷却失败: {e}")
            return True  # 异常时允许发送警报

    # =========================================================================
    # 静态规则拦截器（Level -1 零算力路由）
    # =========================================================================

    STATIC_RULES_PREFIX = "shop:{shop_id}:static_rules"

    def _get_static_rules_key(self, shop_id: str) -> str:
        """获取静态规则的 Redis key"""
        return self.STATIC_RULES_PREFIX.format(shop_id=shop_id)

    def get_static_rules(self, shop_id: str) -> dict:
        """
        获取店铺的静态回复规则

        Args:
            shop_id: 店铺ID

        Returns:
            字典 {关键词: 固定回复}
        """
        if self._client is None:
            logger.warning("Redis 未连接，无法获取静态规则")
            return {}

        try:
            key = self._get_static_rules_key(shop_id)
            rules = self._client.hgetall(key)

            # Fallback: 如果该店铺没有规则，尝试读取 default 规则
            if not rules and shop_id != "default":
                default_key = self._get_static_rules_key("default")
                rules = self._client.hgetall(default_key)
                if rules:
                    logger.debug(f"店铺 {shop_id} 无规则，使用 default 规则: count={len(rules)}")

            logger.debug(f"获取静态规则: shop_id={shop_id}, count={len(rules) if rules else 0}")
            return rules or {}
        except Exception as e:
            logger.error(f"获取静态规则失败: {e}")
            return {}

    def set_static_rule(self, shop_id: str, keyword: str, reply: str) -> bool:
        """
        设置单个静态回复规则

        Args:
            shop_id: 店铺ID
            keyword: 触发关键词
            reply: 固定回复内容

        Returns:
            是否设置成功
        """
        if self._client is None:
            logger.warning("Redis 未连接，无法设置静态规则")
            return False

        try:
            key = self._get_static_rules_key(shop_id)
            self._client.hset(key, keyword, reply)
            logger.info(f"设置静态规则: shop_id={shop_id}, keyword={keyword}")
            return True
        except Exception as e:
            logger.error(f"设置静态规则失败: {e}")
            return False

    def delete_static_rule(self, shop_id: str, keyword: str) -> bool:
        """
        删除单个静态回复规则

        Args:
            shop_id: 店铺ID
            keyword: 触发关键词

        Returns:
            是否删除成功
        """
        if self._client is None:
            logger.warning("Redis 未连接，无法删除静态规则")
            return False

        try:
            key = self._get_static_rules_key(shop_id)
            self._client.hdel(key, keyword)
            logger.info(f"删除静态规则: shop_id={shop_id}, keyword={keyword}")
            return True
        except Exception as e:
            logger.error(f"删除静态规则失败: {e}")
            return False

    def clear_static_rules(self, shop_id: str) -> bool:
        """
        清空店铺的所有静态规则

        Args:
            shop_id: 店铺ID

        Returns:
            是否清空成功
        """
        if self._client is None:
            logger.warning("Redis 未连接，无法清空静态规则")
            return False

        try:
            key = self._get_static_rules_key(shop_id)
            self._client.delete(key)
            logger.info(f"清空静态规则: shop_id={shop_id}")
            return True
        except Exception as e:
            logger.error(f"清空静态规则失败: {e}")
            return False


# 全局单例
redis_manager = RedisManager()
