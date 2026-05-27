import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from Message.workflow.chunk_builder import build_product_chunks, build_sop_chunks
from Message.workflow.sop_loader import SopRecord


def test_product_chunk_has_shop_domain_version_and_price_boundary():
    chunks = build_product_chunks(
        [
            {
                "shop_id": "shop-a",
                "goods_id": "goods-1",
                "goods_name": "Synthetic Cream",
                "price": "99",
                "usage_method": "Use gently",
                "ingredients": "Synthetic ingredient",
            }
        ],
        version="product-v1",
    )

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.shop_id == "shop-a"
    assert chunk.domain == "product_catalog"
    assert chunk.version == "product-v1"
    assert "最终以商品页面/结算页为准" in chunk.content
    assert "raw_db_row" not in chunk.metadata
    assert chunk.metadata["field_flags"]["has_goods_name"] is True
    assert chunk.metadata["field_flags"]["has_goods_id"] is True
    assert chunk.metadata["field_flags"]["has_price_boundary"] is True


def test_product_chunk_domain_can_be_pinned_for_qa():
    chunks = build_product_chunks(
        [{"shop_id": "shop-a", "goods_id": "goods-1", "goods_name": "Synthetic Cream"}],
        version="product-test-v1",
        domain="product_basic",
    )

    assert chunks[0].domain == "product_basic"
    assert chunks[0].source_type == "product"
    assert chunks[0].version == "product-test-v1"


def test_product_chunk_from_real_row_keeps_raw_detail_out_of_metadata():
    chunks = build_product_chunks(
        [
            {
                "shop_id": "shop-a",
                "goods_id": "goods-1",
                "goods_name": "Synthetic Cream",
                "price_min": "88",
                "price_max": "99",
                "raw_detail_json": "RAW_DETAIL_SHOULD_NOT_LEAK",
                "knowledge_status": "active",
                "source_table": "product_knowledge",
            }
        ],
        version="real-product-v1",
        domain="product_catalog",
    )

    assert len(chunks) == 1
    assert "88-99" in chunks[0].content
    assert "最终以商品页面/结算页为准" in chunks[0].content
    assert "raw_detail_json" not in chunks[0].metadata
    assert "RAW_DETAIL_SHOULD_NOT_LEAK" not in str(chunks[0].metadata)
    assert chunks[0].metadata["source_table"] == "product_knowledge"
    assert chunks[0].metadata["knowledge_status"] == "active"
    assert chunks[0].metadata["field_flags"]["has_price_boundary"] is True


def test_sop_record_builds_domain_chunk():
    record = SopRecord(
        kb_item_id="sop-1",
        domain="logistics_policy",
        title="Shipping policy",
        intent_examples=["why not arrived"],
        approved_answer="Use order logistics page as source of truth.",
        forbidden_phrases=["will arrive tomorrow"],
        should_transfer_human=False,
        risk_level="P0",
        version="sop-v1",
        content_hash="hash",
        shop_id="shop-a",
        source="fixture",
    )

    chunks = build_sop_chunks([record])

    assert len(chunks) == 1
    assert chunks[0].domain == "logistics_policy"
    assert chunks[0].shop_id == "shop-a"
    assert chunks[0].version == "sop-v1"


def test_chunk_builder_adds_lifecycle_metadata_without_changing_content_hash():
    record = SopRecord(
        kb_item_id="sop-1",
        domain="logistics_policy",
        title="Shipping policy",
        intent_examples=["why not arrived"],
        approved_answer="Use order logistics page as source of truth.",
        forbidden_phrases=["will arrive tomorrow"],
        should_transfer_human=False,
        risk_level="P0",
        version="sop-v1",
        content_hash="hash",
        shop_id="shop-a",
        source="fixture",
    )

    first = build_sop_chunks([record], index_run_id="run-a", namespace="acceptance", created_by="test")[0]
    second = build_sop_chunks([record], index_run_id="run-b", namespace="acceptance", created_by="test")[0]

    assert first.metadata["index_run_id"] == "run-a"
    assert first.metadata["namespace"] == "acceptance"
    assert first.metadata["created_by"] == "test"
    assert first.metadata["is_test_data"] is False
    assert first.content_hash == second.content_hash
    assert "raw_db_row" not in first.metadata
