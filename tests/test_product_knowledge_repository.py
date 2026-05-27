import json

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, Channel, ProductKnowledge, Shop
from Message.workflow.knowledge import ProductKnowledgeRetriever
from Message.workflow.knowledge_repository import ProductKnowledgeRepository


def _repo():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    raw_detail = {
        "manual_attributes": {
            "sku_summary": "100ml 瓶装",
            "usage_method": "早晚洁面后使用",
            "ingredients": "玫瑰提取物、甘油",
            "shelf_life": "三年",
            "warnings": "敏感肌建议先局部测试",
            "manual_notes": "人工补充说明",
        }
    }

    setup_session = SessionLocal()
    channel = Channel(channel_name="pinduoduo", description="test")
    shop_a = Shop(channel=channel, shop_id="shop-a", shop_name="Shop A")
    shop_b = Shop(channel=channel, shop_id="shop-b", shop_name="Shop B")
    setup_session.add_all(
        [
            channel,
            shop_a,
            shop_b,
            ProductKnowledge(
                shop=shop_a,
                goods_id="rose-water",
                goods_name="玫瑰精华水",
                price="99元",
                specifications="100ml",
                raw_detail_json=json.dumps(raw_detail, ensure_ascii=False),
            ),
            ProductKnowledge(
                shop=shop_b,
                goods_id="green-tea-cream",
                goods_name="绿茶面霜",
                price="129元",
                specifications="50g",
            ),
        ]
    )
    setup_session.commit()
    setup_session.close()

    calls = {"closed": 0, "committed": 0}

    def provider():
        session = SessionLocal()
        original_close = session.close

        def close():
            calls["closed"] += 1
            original_close()

        event.listen(session, "after_commit", lambda _session: calls.__setitem__("committed", calls["committed"] + 1))
        session.close = close
        return session

    return ProductKnowledgeRepository(session_provider=provider), calls


def test_repository_only_loads_requested_shop_products():
    repo, calls = _repo()

    records = repo.load_records(shop_id="shop-a")

    assert calls["closed"] == 1
    assert calls["committed"] == 0
    assert [record["goods_id"] for record in records] == ["rose-water"]
    assert records[0]["shop_id"] == "shop-a"


def test_repository_preserves_manual_attributes_for_retriever_fields():
    repo, _session = _repo()

    record = repo.load_records(shop_id="shop-a")[0]

    assert record["sku_summary"] == "100ml 瓶装"
    assert record["usage_method"] == "早晚洁面后使用"
    assert record["ingredients"] == "玫瑰提取物、甘油"
    assert record["shelf_life"] == "三年"
    assert record["warnings"] == "敏感肌建议先局部测试"
    assert record["manual_notes"] == "人工补充说明"
    assert record["raw_detail_json"]


def test_repository_records_are_usable_by_product_knowledge_retriever():
    repo, _session = _repo()
    retriever = ProductKnowledgeRetriever(repo.load_records(shop_id="shop-a"))

    shop_a_hits = retriever.search(
        shop_id="shop-a",
        domain="product_basic",
        query="玫瑰精华水成分是什么",
    )
    shop_b_hits = retriever.search(
        shop_id="shop-b",
        domain="product_basic",
        query="玫瑰精华水成分是什么",
    )

    assert len(shop_a_hits) == 1
    assert shop_a_hits[0].metadata["goods_id"] == "rose-water"
    assert "玫瑰提取物" in shop_a_hits[0].content
    assert shop_b_hits == []
