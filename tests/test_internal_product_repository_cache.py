import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
import pytest

from Message.workflow.knowledge_repository import ProductKnowledgeRepository


def _record(shop_id: str, goods_id: str = "goods") -> dict:
    return {
        "shop_id": shop_id,
        "domain": "product_catalog",
        "goods_id": goods_id,
        "goods_name": f"Product {goods_id}",
        "usage_method": "Use after cleansing",
    }


def test_default_cache_ttl_is_300(monkeypatch):
    monkeypatch.delenv(ProductKnowledgeRepository.CACHE_TTL_ENV_VAR, raising=False)

    repo = ProductKnowledgeRepository(records_source=[])

    assert repo._ttl_seconds == 300.0


def test_cache_ttl_uses_valid_env(monkeypatch):
    monkeypatch.setenv(ProductKnowledgeRepository.CACHE_TTL_ENV_VAR, "42.5")

    repo = ProductKnowledgeRepository(records_source=[])

    assert repo._ttl_seconds == 42.5


@pytest.mark.parametrize("env_value", ["invalid", "", " ", "-1"])
def test_invalid_cache_ttl_env_falls_back_to_300(monkeypatch, env_value):
    monkeypatch.setenv(ProductKnowledgeRepository.CACHE_TTL_ENV_VAR, env_value)

    repo = ProductKnowledgeRepository(records_source=[])

    assert repo._ttl_seconds == 300.0


def test_cache_ttl_zero_disables_cache(monkeypatch):
    monkeypatch.setenv(ProductKnowledgeRepository.CACHE_TTL_ENV_VAR, "0")
    calls = []

    def source(shop_id):
        calls.append(shop_id)
        return [_record(shop_id, goods_id=f"goods-{len(calls)}")]

    repo = ProductKnowledgeRepository(records_source=source)

    assert repo.load_records(shop_id="shop-a")[0]["goods_id"] == "goods-1"
    assert repo.load_records(shop_id="shop-a")[0]["goods_id"] == "goods-2"
    assert calls == ["shop-a", "shop-a"]
    assert repo._cache == {}


def test_cache_miss_then_hit_reuses_loaded_shop_records():
    now = [100.0]
    calls = []

    def source(shop_id):
        calls.append(shop_id)
        return [_record(shop_id)]

    repo = ProductKnowledgeRepository(records_source=source, time_provider=lambda: now[0], ttl_seconds=300)

    first = repo.load_shop_products("shop-a")
    second = repo.load_shop_products("shop-a")

    assert calls == ["shop-a"]
    assert first == second
    assert first is not second


def test_ttl_expiry_reloads_shop_records():
    now = [100.0]
    calls = []

    def source(shop_id):
        calls.append((shop_id, len(calls)))
        return [_record(shop_id, goods_id=f"goods-{len(calls)}")]

    repo = ProductKnowledgeRepository(records_source=source, time_provider=lambda: now[0], ttl_seconds=5)

    assert repo.load_records(shop_id="shop-a")[0]["goods_id"] == "goods-1"
    now[0] = 104.0
    assert repo.load_records(shop_id="shop-a")[0]["goods_id"] == "goods-1"
    now[0] = 106.0
    assert repo.load_records(shop_id="shop-a")[0]["goods_id"] == "goods-2"
    assert len(calls) == 2


def test_clear_cache_shop_id_only_clears_that_shop():
    calls = []

    def source(shop_id):
        calls.append(shop_id)
        return [_record(shop_id)]

    repo = ProductKnowledgeRepository(records_source=source)
    repo.load_records(shop_id="shop-a")
    repo.load_records(shop_id="shop-b")

    repo.clear_cache("shop-a")
    repo.load_records(shop_id="shop-a")
    repo.load_records(shop_id="shop-b")

    assert calls == ["shop-a", "shop-b", "shop-a"]


def test_clear_cache_without_shop_id_clears_all_shops():
    calls = []

    def source(shop_id):
        calls.append(shop_id)
        return [_record(shop_id)]

    repo = ProductKnowledgeRepository(records_source=source)
    repo.load_records(shop_id="shop-a")
    repo.load_records(shop_id="shop-b")

    repo.clear_cache()
    repo.load_records(shop_id="shop-a")
    repo.load_records(shop_id="shop-b")

    assert calls == ["shop-a", "shop-b", "shop-a", "shop-b"]


def test_cache_isolated_by_shop_id():
    calls = []

    def source(shop_id):
        calls.append(shop_id)
        return [_record(shop_id, goods_id=f"{shop_id}-goods")]

    repo = ProductKnowledgeRepository(records_source=source)

    shop_a = repo.load_records(shop_id="shop-a")
    shop_b = repo.load_records(shop_id="shop-b")
    shop_a_again = repo.load_records(shop_id="shop-a")

    assert [record["shop_id"] for record in shop_a] == ["shop-a"]
    assert [record["shop_id"] for record in shop_b] == ["shop-b"]
    assert shop_a_again == shop_a
    assert calls == ["shop-a", "shop-b"]


def test_db_exception_returns_empty_records_and_does_not_raise():
    calls = []

    def source(shop_id):
        calls.append(shop_id)
        raise RuntimeError("database unavailable")

    repo = ProductKnowledgeRepository(records_source=source)

    assert repo.load_records(shop_id="shop-a") == []
    assert repo.load_records(shop_id="shop-a") == []
    assert calls == ["shop-a"]


def test_empty_shop_id_returns_empty_without_full_scan():
    calls = []

    def source(shop_id):
        calls.append(shop_id)
        return [_record(shop_id)]

    repo = ProductKnowledgeRepository(records_source=source)

    assert repo.load_records(shop_id="") == []
    assert repo.load_shop_products(None) == []
    assert calls == []
