"""
集中式配置管理模块

统一管理系统参数，支持环境变量覆盖。
解决硬编码问题，提高配置可维护性。

V2.0 战役七：上线预备重构
"""
import os

# =============================================================================
# TTL 时间配置 (秒)
# =============================================================================

# 人工接管锁有效期（默认 4 分钟）
HUMAN_LOCK_TTL = int(os.getenv("HUMAN_LOCK_TTL", "240"))

# AI 推理互斥锁有效期（默认 10 秒）
INFERENCE_LOCK_TTL = int(os.getenv("INFERENCE_LOCK_TTL", "10"))

# 意图缓存有效期（默认 10 分钟）
INTENT_CACHE_TTL = int(os.getenv("INTENT_CACHE_TTL", "600"))

# 警报冷却防抖时间（默认 60 秒）
ALERT_COOLDOWN_TTL = int(os.getenv("ALERT_COOLDOWN_TTL", "60"))

# AI 苏醒标记有效期（默认 30 秒）
AI_AWAKENING_TTL = int(os.getenv("AI_AWAKENING_TTL", "30"))


# =============================================================================
# 意图判定配置
# =============================================================================

# 极短句判定阈值（字符数，默认 5）
# 小于等于此值的输入将被判定为极短句，触发意图继承
SHORT_SENTENCE_THRESHOLD = int(os.getenv("SHORT_SENTENCE_THRESHOLD", "5"))


# =============================================================================
# Redis 连接配置
# =============================================================================

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "123456")
REDIS_DB = int(os.getenv("REDIS_DB", "0"))


# =============================================================================
# 配置验证函数
# =============================================================================

def validate_config() -> bool:
    """
    验证配置有效性

    Returns:
        True 如果所有配置有效
    """
    errors = []

    if HUMAN_LOCK_TTL <= 0:
        errors.append(f"HUMAN_LOCK_TTL 必须大于 0，当前值: {HUMAN_LOCK_TTL}")

    if INFERENCE_LOCK_TTL <= 0:
        errors.append(f"INFERENCE_LOCK_TTL 必须大于 0，当前值: {INFERENCE_LOCK_TTL}")

    if INTENT_CACHE_TTL <= 0:
        errors.append(f"INTENT_CACHE_TTL 必须大于 0，当前值: {INTENT_CACHE_TTL}")

    if ALERT_COOLDOWN_TTL <= 0:
        errors.append(f"ALERT_COOLDOWN_TTL 必须大于 0，当前值: {ALERT_COOLDOWN_TTL}")

    if errors:
        from utils.logger_loguru import get_logger
        logger = get_logger("Config")
        for error in errors:
            logger.error(error)
        return False

    return True
