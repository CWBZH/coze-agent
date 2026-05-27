import pytest

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from Message.workflow.rag_types import KnowledgeChunk, RetrievalQuery
from Message.workflow.vector_store import InMemoryVectorStore


def _chunk(chunk_id, shop_id, domain, content, version="v1"):
    return KnowledgeChunk(
        chunk_id=chunk_id,
        shop_id=shop_id,
        domain=domain,
        source_type="synthetic",
        source_id=chunk_id,
        title=f"title-{chunk_id}",
        content=content,
        version=version,
    )


def test_in_memory_store_filters_shop_domain_version_and_top_k():
    store = InMemoryVectorStore()
    store.upsert(_chunk("a1", "shop-a", "logistics_policy", "shipping arrival policy", "v1"), [1, 0])
    store.upsert(_chunk("a2", "shop-a", "after_sales_evidence", "broken item photos", "v1"), [0, 1])
    store.upsert(_chunk("b1", "shop-b", "logistics_policy", "other shop shipping", "v1"), [1, 0])
    store.upsert(_chunk("a3", "shop-a", "logistics_policy", "old shipping", "v0"), [1, 0])

    hits = store.search(
        RetrievalQuery(shop_id="shop-a", domain="logistics_policy", query="shipping", top_k=1, version="v1"),
        [1, 0],
    )

    assert [hit.chunk_id for hit in hits] == ["a1"]
    assert all(hit.shop_id == "shop-a" for hit in hits)
    assert all(hit.domain == "logistics_policy" for hit in hits)
    assert all(hit.version == "v1" for hit in hits)


def test_store_rejects_empty_shop_or_domain():
    store = InMemoryVectorStore()

    with pytest.raises(ValueError):
        store.search(RetrievalQuery(shop_id="", domain="logistics_policy", query="x"), [1])
    with pytest.raises(ValueError):
        store.search(RetrievalQuery(shop_id="shop-a", domain="", query="x"), [1])


def test_upsert_is_idempotent_by_chunk_id():
    store = InMemoryVectorStore()
    chunk = _chunk("same", "shop-a", "product_catalog", "product content")

    store.upsert(chunk, [1, 0])
    store.upsert(chunk, [1, 0])

    hits = store.search(RetrievalQuery(shop_id="shop-a", domain="product_catalog", query="product"), [1, 0])
    assert len(hits) == 1


def test_delete_chunks_requires_safe_filters():
    store = InMemoryVectorStore()
    store.upsert(_chunk("safe", "shop-a", "logistics_policy", "content"), [1, 0])

    assert store.delete_chunks().status == "rejected"
    assert store.delete_chunks(shop_id="shop-a").status == "rejected"
    assert store.delete_chunks(domain="logistics_policy").status == "rejected"


def test_delete_chunks_dry_run_and_pollution_cleanup():
    store = InMemoryVectorStore()
    pollution = KnowledgeChunk(
        chunk_id="pollution",
        shop_id="shop-a",
        domain="logistics_policy",
        source_type="pollution_wrong_shop",
        source_id="pollution-1",
        title="pollution",
        content="pollution content",
        version="v1",
        metadata={"namespace": "acceptance", "is_test_data": True, "index_run_id": "run-1"},
    )
    sop = KnowledgeChunk(
        chunk_id="sop",
        shop_id="shop-a",
        domain="logistics_policy",
        source_type="sop",
        source_id="sop-1",
        title="sop",
        content="sop content",
        version="v1",
        metadata={"namespace": "acceptance", "is_test_data": False, "index_run_id": "run-1"},
    )
    store.upsert(pollution, [1, 0])
    store.upsert(sop, [1, 0])

    dry_run = store.delete_chunks(source_type_prefix="pollution_", namespace="acceptance", dry_run=True)
    assert dry_run.status == "ok"
    assert dry_run.matched_count == 1
    assert dry_run.deleted_count == 0
    assert len(store.search(RetrievalQuery(shop_id="shop-a", domain="logistics_policy", query="x"), [1, 0])) == 2

    deleted = store.delete_chunks(source_type_prefix="pollution_", namespace="acceptance")
    assert deleted.status == "ok"
    assert deleted.deleted_count == 1
    hits = store.search(RetrievalQuery(shop_id="shop-a", domain="logistics_policy", query="x"), [1, 0])
    assert [hit.chunk_id for hit in hits] == ["sop"]


def test_delete_chunks_by_index_run_id_keeps_other_runs():
    store = InMemoryVectorStore()
    first = KnowledgeChunk(
        chunk_id="first",
        shop_id="shop-a",
        domain="logistics_policy",
        source_type="pollution_old_version",
        source_id="p1",
        title="first",
        content="first",
        version="v1",
        metadata={"namespace": "acceptance", "is_test_data": True, "index_run_id": "run-1"},
    )
    second = KnowledgeChunk(
        chunk_id="second",
        shop_id="shop-a",
        domain="logistics_policy",
        source_type="pollution_old_version",
        source_id="p2",
        title="second",
        content="second",
        version="v1",
        metadata={"namespace": "acceptance", "is_test_data": True, "index_run_id": "run-2"},
    )
    store.upsert(first, [1, 0])
    store.upsert(second, [1, 0])

    result = store.delete_chunks(index_run_id="run-1")

    assert result.status == "ok"
    assert result.deleted_count == 1
    hits = store.search(RetrievalQuery(shop_id="shop-a", domain="logistics_policy", query="x"), [1, 0])
    assert [hit.chunk_id for hit in hits] == ["second"]


def test_legacy_pollution_audit_detects_only_pollution_sources():
    store = InMemoryVectorStore()
    legacy = KnowledgeChunk(
        chunk_id="legacy-old-version",
        shop_id="synthetic-shop-1",
        domain="logistics_policy",
        source_type="pollution_old_version",
        source_id="pollution-legacy",
        title="legacy",
        content="legacy pollution content",
        version="old-version",
        metadata={},
    )
    sop = KnowledgeChunk(
        chunk_id="normal-sop",
        shop_id="synthetic-shop-1",
        domain="logistics_policy",
        source_type="sop",
        source_id="sop-1",
        title="sop",
        content="normal sop content",
        version="sop-test-v1",
        metadata={},
    )
    store.upsert(legacy, [1, 0])
    store.upsert(sop, [1, 0])

    result = store.audit_legacy_pollution(source_type_prefix="pollution_")

    assert result.status == "ok"
    assert result.legacy_candidate_count == 1
    assert result.legacy_source_types == ["pollution_old_version"]
    assert result.legacy_versions == ["old-version"]
    assert result.has_non_pollution_candidates is False


def test_legacy_cleanup_requires_pollution_prefix_and_strong_filter():
    store = InMemoryVectorStore()
    legacy = KnowledgeChunk(
        chunk_id="legacy-old-version",
        shop_id="synthetic-shop-1",
        domain="logistics_policy",
        source_type="pollution_old_version",
        source_id="pollution-legacy",
        title="legacy",
        content="legacy pollution content",
        version="old-version",
        metadata={},
    )
    sop = KnowledgeChunk(
        chunk_id="normal-sop",
        shop_id="synthetic-shop-1",
        domain="logistics_policy",
        source_type="sop",
        source_id="sop-1",
        title="sop",
        content="normal sop content",
        version="sop-test-v1",
        metadata={},
    )
    store.upsert(legacy, [1, 0])
    store.upsert(sop, [1, 0])

    weak = store.delete_legacy_pollution(source_type_prefix="pollution_", dry_run=False)
    deleted = store.delete_legacy_pollution(
        source_type_prefix="pollution_",
        version="old-version",
        dry_run=False,
    )

    assert weak.status == "rejected"
    assert weak.error_type == "unsafe_legacy_filters"
    assert deleted.status == "ok"
    assert deleted.deleted_count == 1
    hits = store.search(RetrievalQuery(shop_id="synthetic-shop-1", domain="logistics_policy", query="x"), [1, 0])
    assert [hit.chunk_id for hit in hits] == ["normal-sop"]
