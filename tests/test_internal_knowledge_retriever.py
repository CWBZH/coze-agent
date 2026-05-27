import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from Message.workflow.knowledge import ProductKnowledgeRetriever


def _records():
    return [
        {
            "shop_id": "shop-a",
            "domain": "product_catalog",
            "goods_id": "goods-a",
            "goods_name": "玫瑰精华水",
            "price": "99元",
            "specifications": "100ml",
            "usage_method": "早晚洁面后使用",
            "ingredients": "玫瑰提取物、甘油",
            "shelf_life": "三年",
            "warnings": "敏感肌建议先局部测试",
            "fastgpt_question": "玫瑰精华水怎么用",
            "fastgpt_answer": "早晚洁面后取适量使用。",
        },
        {
            "shop_id": "shop-b",
            "domain": "product_catalog",
            "goods_id": "goods-b",
            "goods_name": "绿茶面霜",
            "price": "129元",
            "specifications": "50g",
            "usage_method": "取适量涂抹面部",
            "ingredients": "绿茶提取物",
            "shelf_life": "两年",
        },
    ]


def test_product_retriever_keeps_shop_isolation():
    retriever = ProductKnowledgeRetriever(_records())

    shop_a_hits = retriever.search(shop_id="shop-a", domain="product_basic", query="绿茶面霜多少钱")
    shop_b_hits = retriever.search(shop_id="shop-b", domain="product_basic", query="绿茶面霜多少钱")

    assert shop_a_hits == []
    assert len(shop_b_hits) == 1
    assert shop_b_hits[0].title == "绿茶面霜"


def test_product_retriever_matches_product_fields():
    retriever = ProductKnowledgeRetriever(_records())

    hits = retriever.search(shop_id="shop-a", domain="product_basic", query="玫瑰精华水成分是什么")

    assert len(hits) == 1
    assert hits[0].title == "玫瑰精华水"
    assert hits[0].domain == "product_catalog"
    assert hits[0].score > 0
    assert "玫瑰提取物" in hits[0].content


def test_product_retriever_returns_empty_below_threshold():
    retriever = ProductKnowledgeRetriever(_records())

    assert retriever.search(shop_id="shop-a", domain="product_basic", query="完全无关的问题") == []
