"""
V3 Redis tenant key isolation primitive.

Provides a pure key-building primitive for multi-tenant Redis key isolation.
Key format: {namespace}:{shop_id}:{platform}:{buyer_id}:{suffix}
"""

import re
from dataclasses import dataclass


# Suffix constants
SUFFIX_SESSION = "session"
SUFFIX_LOCKED_GOODS = "locked_goods"
SUFFIX_PRODUCT_MEMORY = "product_memory"
SUFFIX_HUMAN_LOCK = "human_lock"
SUFFIX_INFERENCE_LOCK = "inference_lock"
SUFFIX_INTENT_CACHE = "intent_cache"
SUFFIX_AI_AWAKENING = "ai_awakening"
SUFFIX_ALERT_COOLDOWN = "alert_cooldown"


@dataclass
class TenantContext:
    """Tenant context for Redis key building.

    Attributes:
        shop_id: Shop identifier (must be non-empty)
        buyer_id: Buyer identifier (must be non-empty)
        platform: Platform identifier (defaults to 'pdd')
    """
    shop_id: str
    buyer_id: str
    platform: str = "pdd"


class V3RedisKeyBuilder:
    """Redis key builder for V3 tenant isolation.

    Builds Redis keys with format: {namespace}:{shop_id}:{platform}:{buyer_id}:{suffix}

    Attributes:
        namespace: Redis key namespace (defaults to 'csa')
    """

    def __init__(self, namespace: str = "csa"):
        """Initialize key builder with namespace.

        Args:
            namespace: Redis key namespace (default: 'csa')
        """
        self.namespace = namespace

    def _sanitize(self, value: str) -> str:
        """Sanitize a key part to be Redis-safe.

        - Strips leading/trailing whitespace
        - Replaces colons with underscores
        - Replaces whitespace runs with single underscore
        - Preserves Chinese characters

        Args:
            value: String to sanitize

        Returns:
            Sanitized string
        """
        value = value.strip()
        value = re.sub(r':', '_', value)  # Replace colons
        value = re.sub(r'\s+', '_', value)  # Replace whitespace runs with single underscore
        return value

    def build(self, ctx: TenantContext, suffix: str) -> str:
        """Build a Redis key from tenant context and suffix.

        Args:
            ctx: Tenant context with shop_id, buyer_id, and platform
            suffix: Key suffix (e.g., 'session', 'human_lock')

        Returns:
            Redis key in format: {namespace}:{shop_id}:{platform}:{buyer_id}:{suffix}

        Raises:
            ValueError: If shop_id, buyer_id, platform, or suffix is empty after stripping
        """
        # Validate and sanitize inputs
        shop_id = ctx.shop_id.strip()
        if not shop_id:
            raise ValueError("shop_id is required and cannot be empty")

        buyer_id = ctx.buyer_id.strip()
        if not buyer_id:
            raise ValueError("buyer_id is required and cannot be empty")

        platform = ctx.platform.strip()
        if not platform:
            raise ValueError("platform is required and cannot be empty")

        suffix = suffix.strip()
        if not suffix:
            raise ValueError("suffix is required and cannot be empty")

        # Sanitize all parts
        shop_id = self._sanitize(shop_id)
        buyer_id = self._sanitize(buyer_id)
        platform = self._sanitize(platform.lower())
        suffix = self._sanitize(suffix)

        # Build key
        return f"{self.namespace}:{shop_id}:{platform}:{buyer_id}:{suffix}"

    # Convenience methods

    def session(self, ctx: TenantContext) -> str:
        """Build session key."""
        return self.build(ctx, SUFFIX_SESSION)

    def locked_goods(self, ctx: TenantContext) -> str:
        """Build locked goods key."""
        return self.build(ctx, SUFFIX_LOCKED_GOODS)

    def product_memory(self, ctx: TenantContext) -> str:
        """Build product memory key."""
        return self.build(ctx, SUFFIX_PRODUCT_MEMORY)

    def human_lock(self, ctx: TenantContext) -> str:
        """Build human lock key."""
        return self.build(ctx, SUFFIX_HUMAN_LOCK)

    def inference_lock(self, ctx: TenantContext) -> str:
        """Build inference lock key."""
        return self.build(ctx, SUFFIX_INFERENCE_LOCK)

    def intent_cache(self, ctx: TenantContext) -> str:
        """Build intent cache key."""
        return self.build(ctx, SUFFIX_INTENT_CACHE)

    def ai_awakening(self, ctx: TenantContext) -> str:
        """Build AI awakening key."""
        return self.build(ctx, SUFFIX_AI_AWAKENING)

    def alert_cooldown(self, ctx: TenantContext) -> str:
        """Build alert cooldown key."""
        return self.build(ctx, SUFFIX_ALERT_COOLDOWN)
