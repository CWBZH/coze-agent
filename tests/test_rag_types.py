import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from Message.workflow.rag_types import KnowledgeChunk, RetrievalHit, RetrievalQuery, stable_content_hash


def test_retrieval_query_requires_shop_and_domain():
    assert RetrievalQuery(shop_id="", domain="product_catalog", query="x").validate() == [
        "shop_id is required"
    ]
    assert RetrievalQuery(shop_id="shop-a", domain="", query="x").validate() == [
        "domain is required"
    ]


def test_content_hash_and_summary_are_stable_and_short():
    content = "This is a long synthetic product detail " * 20
    chunk = KnowledgeChunk(
        chunk_id="chunk-1",
        shop_id="shop-a",
        domain="product_catalog",
        source_type="product",
        source_id="goods-1",
        title="Synthetic Product",
        content=content,
        version="v1",
    )

    assert chunk.content_hash == stable_content_hash(content)
    hit = RetrievalHit.from_chunk(chunk, score=0.9)
    assert len(hit.content_summary) <= 123
    assert hit.content_summary != content
