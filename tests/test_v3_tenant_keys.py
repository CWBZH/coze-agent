"""
Tests for V3 Redis tenant key isolation primitive.
TDD: Tests written first, then implementation.
"""

import pytest
import sys
import importlib.util
from pathlib import Path
from dataclasses import dataclass

# Load v3_tenant_keys module directly without triggering __init__.py
# This avoids dependency on services that aren't initialized in test context
module_path = Path(__file__).parent.parent / "Agent" / "CustomerAgent" / "custom" / "v3_tenant_keys.py"
spec = importlib.util.spec_from_file_location("v3_tenant_keys", module_path)
v3_tenant_keys_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v3_tenant_keys_module)

TenantContext = v3_tenant_keys_module.TenantContext
V3RedisKeyBuilder = v3_tenant_keys_module.V3RedisKeyBuilder


class TestTenantContext:
    """Test TenantContext dataclass."""

    def test_tenant_context_creation(self):
        """Test basic TenantContext creation."""
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        assert ctx.shop_id == "shopA"
        assert ctx.buyer_id == "buyer001"
        assert ctx.platform == "pdd"

    def test_tenant_context_custom_platform(self):
        """Test TenantContext with custom platform."""
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001", platform="TAOBAO")
        assert ctx.platform == "TAOBAO"


class TestV3RedisKeyBuilderCanonicalFormat:
    """Test canonical key format."""

    def test_canonical_key_format(self):
        """Test canonical key format: csa:{shop_id}:{platform}:{buyer_id}:{suffix}"""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        key = builder.build(ctx, "session")
        assert key == "csa:shopA:pdd:buyer001:session"

    def test_key_with_custom_platform(self):
        """Test key with custom platform."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001", platform="TAOBAO")
        key = builder.build(ctx, "product_memory")
        assert key == "csa:shopA:taobao:buyer001:product_memory"


class TestTenantIsolation:
    """Test tenant isolation."""

    def test_different_shop_isolates_same_buyer(self):
        """Different shop_id isolates same buyer_id."""
        builder = V3RedisKeyBuilder()
        ctx1 = TenantContext(shop_id="shopA", buyer_id="buyer001")
        ctx2 = TenantContext(shop_id="shopB", buyer_id="buyer001")

        key1 = builder.build(ctx1, "session")
        key2 = builder.build(ctx2, "session")

        assert key1 != key2
        assert "shopA" in key1
        assert "shopB" in key2

    def test_different_buyer_isolates_same_shop(self):
        """Different buyer_id isolates same shop_id."""
        builder = V3RedisKeyBuilder()
        ctx1 = TenantContext(shop_id="shopA", buyer_id="buyer001")
        ctx2 = TenantContext(shop_id="shopA", buyer_id="buyer002")

        key1 = builder.build(ctx1, "session")
        key2 = builder.build(ctx2, "session")

        assert key1 != key2
        assert "buyer001" in key1
        assert "buyer002" in key2


class TestPlatformHandling:
    """Test platform handling."""

    def test_default_platform_is_pdd(self):
        """Default platform is pdd."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        key = builder.build(ctx, "session")
        assert ":pdd:" in key

    def test_custom_platform_lowercased(self):
        """Custom platform is lowercased."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001", platform="TAOBAO")
        key = builder.build(ctx, "session")
        assert ":taobao:" in key

    def test_platform_sanitized(self):
        """Platform with special chars is sanitized."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001", platform="TAO BAO")
        key = builder.build(ctx, "session")
        assert ":tao_bao:" in key


class TestSanitization:
    """Test key sanitization."""

    def test_colon_sanitization(self):
        """Colon in shop_id/buyer_id is replaced with underscore."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shop:A", buyer_id="buyer:001")
        key = builder.build(ctx, "session")
        assert "shop_A" in key
        assert "buyer_001" in key
        # Verify the original colon in shop_id and buyer_id was replaced
        assert "shop:A" not in key
        assert "buyer:001" not in key

    def test_whitespace_sanitization(self):
        """Whitespace runs are replaced with single underscore."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shop  A", buyer_id="buyer  001")
        key = builder.build(ctx, "session")
        # Multiple spaces become single underscore
        assert "shop_A" in key
        assert "buyer_001" in key
        # Verify no spaces remain
        assert " " not in key

    def test_chinese_characters_preserved(self):
        """Chinese characters in shop/buyer ids are preserved."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="店铺A", buyer_id="买家001")
        key = builder.build(ctx, "session")
        assert "店铺A" in key
        assert "买家001" in key


class TestValidation:
    """Test validation and error handling."""

    def test_missing_shop_id_raises_valueerror(self):
        """Missing shop_id raises ValueError mentioning shop_id."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="", buyer_id="buyer001")
        with pytest.raises(ValueError) as exc_info:
            builder.build(ctx, "session")
        assert "shop_id" in str(exc_info.value)

    def test_missing_buyer_id_raises_valueerror(self):
        """Missing buyer_id raises ValueError mentioning buyer_id."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="")
        with pytest.raises(ValueError) as exc_info:
            builder.build(ctx, "session")
        assert "buyer_id" in str(exc_info.value)

    def test_missing_suffix_raises_valueerror(self):
        """Missing suffix raises ValueError mentioning suffix."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        with pytest.raises(ValueError) as exc_info:
            builder.build(ctx, "")
        assert "suffix" in str(exc_info.value)

    def test_whitespace_only_shop_id_raises_valueerror(self):
        """Whitespace-only shop_id raises ValueError."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="   ", buyer_id="buyer001")
        with pytest.raises(ValueError) as exc_info:
            builder.build(ctx, "session")
        assert "shop_id" in str(exc_info.value)

    def test_whitespace_only_buyer_id_raises_valueerror(self):
        """Whitespace-only buyer_id raises ValueError."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="   ")
        with pytest.raises(ValueError) as exc_info:
            builder.build(ctx, "session")
        assert "buyer_id" in str(exc_info.value)


class TestConvenienceMethods:
    """Test convenience methods."""

    def test_session_method(self):
        """Test session() convenience method."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        key = builder.session(ctx)
        assert key.endswith(":session")

    def test_locked_goods_method(self):
        """Test locked_goods() convenience method."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        key = builder.locked_goods(ctx)
        assert key.endswith(":locked_goods")

    def test_product_memory_method(self):
        """Test product_memory() convenience method."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        key = builder.product_memory(ctx)
        assert key.endswith(":product_memory")

    def test_human_lock_method(self):
        """Test human_lock() convenience method."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        key = builder.human_lock(ctx)
        assert key.endswith(":human_lock")

    def test_inference_lock_method(self):
        """Test inference_lock() convenience method."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        key = builder.inference_lock(ctx)
        assert key.endswith(":inference_lock")

    def test_intent_cache_method(self):
        """Test intent_cache() convenience method."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        key = builder.intent_cache(ctx)
        assert key.endswith(":intent_cache")

    def test_ai_awakening_method(self):
        """Test ai_awakening() convenience method."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        key = builder.ai_awakening(ctx)
        assert key.endswith(":ai_awakening")

    def test_alert_cooldown_method(self):
        """Test alert_cooldown() convenience method."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        key = builder.alert_cooldown(ctx)
        assert key.endswith(":alert_cooldown")


class TestNamespaceOverride:
    """Test namespace override."""

    def test_namespace_override(self):
        """Namespace override works, e.g. namespace=csa_v3."""
        builder = V3RedisKeyBuilder(namespace="csa_v3")
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        key = builder.build(ctx, "session")
        assert key.startswith("csa_v3:")
        assert key == "csa_v3:shopA:pdd:buyer001:session"

    def test_default_namespace_is_csa(self):
        """Default namespace is csa."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        key = builder.build(ctx, "session")
        assert key.startswith("csa:")


class TestEdgeCases:
    """Test edge cases."""

    def test_platform_with_colon_sanitized(self):
        """Platform with colon is sanitized."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001", platform="tao:bao")
        key = builder.build(ctx, "session")
        assert ":tao_bao:" in key

    def test_suffix_with_whitespace_sanitized(self):
        """Suffix with whitespace is sanitized."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        key = builder.build(ctx, "my suffix")
        assert key.endswith(":my_suffix")

    def test_suffix_with_colon_sanitized(self):
        """Suffix with colon is sanitized."""
        builder = V3RedisKeyBuilder()
        ctx = TenantContext(shop_id="shopA", buyer_id="buyer001")
        key = builder.build(ctx, "my:suffix")
        assert key.endswith(":my_suffix")
