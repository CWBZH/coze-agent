import json

import Session.session_manager  # noqa: F401 - keep logger import order stable.
from Message.workflow.rag_types import RetrievalHit
from scripts.acceptance import internal_rag_retrieval_qa


def test_fake_rag_retrieval_qa_passes():
    payload = internal_rag_retrieval_qa.run_qa(
        internal_rag_retrieval_qa.parse_args(["--json-only"])
    )

    assert payload["status"] == "passed"
    assert payload["total"] >= 20
    assert payload["failed"] == 0
    assert payload["retrieval_hit_rate"] >= 0.9
    assert payload["domain_match_rate"] >= 0.9
    assert payload["version_match_rate"] == 1.0
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "Please check the order logistics page" not in rendered
    assert "postgresql://" not in rendered


def test_rag_retrieval_qa_filters_case_id_and_domain():
    one = internal_rag_retrieval_qa.run_qa(
        internal_rag_retrieval_qa.parse_args(["--case-id", "rag-logistics-001", "--json-only"])
    )
    domain = internal_rag_retrieval_qa.run_qa(
        internal_rag_retrieval_qa.parse_args(["--domain", "promotion_policy", "--json-only"])
    )

    assert one["total"] == 1
    assert one["results"][0]["case_id"] == "rag-logistics-001"
    assert domain["total"] == 4
    assert {row["domain"] for row in domain["results"]} == {"promotion_policy"}


def test_rag_retrieval_qa_wrong_version_fails():
    payload = internal_rag_retrieval_qa.run_qa(
        internal_rag_retrieval_qa.parse_args(["--version", "old-version", "--json-only"])
    )

    assert payload["status"] == "failed"
    assert payload["failed"] > 0
    assert payload["version_match_rate"] < 1.0


def test_rag_retrieval_qa_real_mode_requires_pg_dsn():
    payload = internal_rag_retrieval_qa.run_qa(
        internal_rag_retrieval_qa.parse_args(["--real", "--json-only"])
    )

    assert payload["status"] == "error"
    assert payload["failed"] == 1
    assert payload["calls_ollama"] is False
    assert payload["connects_pgvector"] is False


def test_rag_retrieval_qa_pollution_fixture_does_not_leak_with_filters():
    payload = internal_rag_retrieval_qa.run_qa(
        internal_rag_retrieval_qa.parse_args(
            [
                "--pollution-fixture",
                "--pollution-kind",
                "all",
                "--pollution-domain",
                "unrelated_policy",
                "--run-pollution-tests",
                "--fail-on-cross-shop",
                "--fail-on-cross-domain",
                "--fail-on-wrong-version",
                "--json-only",
            ]
        )
    )

    assert payload["status"] == "passed"
    assert payload["pollution_status"] == "passed"
    assert payload["cross_shop_failures"] == 0
    assert payload["cross_domain_failures"] == 0
    assert payload["wrong_version_failures"] == 0


class _StaticEmbedder:
    model = "fake"

    def embed(self, text):
        class _Vector:
            vector = [1.0, 0.0, 0.0]

        return _Vector()


class _LeakyStore:
    def __init__(self, hit):
        self.hit = hit

    def search(self, query, vector):
        return [self.hit]


def _run_with_leaky_hit(monkeypatch, hit, *extra_args):
    monkeypatch.setattr(
        internal_rag_retrieval_qa,
        "_build_retrieval_stack",
        lambda args: (_StaticEmbedder(), _LeakyStore(hit)),
    )
    return internal_rag_retrieval_qa.run_qa(
        internal_rag_retrieval_qa.parse_args(
            [
                "--case-id",
                "rag-logistics-001",
                "--run-pollution-tests",
                *extra_args,
                "--json-only",
            ]
        )
    )


def test_rag_retrieval_qa_detects_wrong_shop_pollution(monkeypatch):
    payload = _run_with_leaky_hit(
        monkeypatch,
        RetrievalHit(
            chunk_id="bad-shop",
            shop_id="synthetic-shop-2",
            domain="logistics_policy",
            title="masked",
            content_summary="masked",
            score=1.0,
            source_type="sop",
            source_id="sop-logistics-001",
            version="sop-test-v1",
            content_hash="hash",
        ),
        "--fail-on-cross-shop",
    )

    assert payload["status"] == "failed"
    assert payload["cross_shop_failures"] == 1
    assert payload["results"][0]["cross_shop_detected"] is True


def test_rag_retrieval_qa_detects_wrong_domain_pollution(monkeypatch):
    payload = _run_with_leaky_hit(
        monkeypatch,
        RetrievalHit(
            chunk_id="bad-domain",
            shop_id="synthetic-shop-1",
            domain="after_sales_evidence",
            title="masked",
            content_summary="masked",
            score=1.0,
            source_type="sop",
            source_id="sop-after-sales-001",
            version="sop-test-v1",
            content_hash="hash",
        ),
        "--fail-on-cross-domain",
    )

    assert payload["status"] == "failed"
    assert payload["cross_domain_failures"] == 1
    assert payload["results"][0]["cross_domain_detected"] is True


def test_rag_retrieval_qa_detects_wrong_version_pollution(monkeypatch):
    payload = _run_with_leaky_hit(
        monkeypatch,
        RetrievalHit(
            chunk_id="bad-version",
            shop_id="synthetic-shop-1",
            domain="logistics_policy",
            title="masked",
            content_summary="masked",
            score=1.0,
            source_type="sop",
            source_id="sop-logistics-001",
            version="old-version",
            content_hash="hash",
        ),
        "--fail-on-wrong-version",
    )

    assert payload["status"] == "failed"
    assert payload["wrong_version_failures"] == 1
    assert payload["results"][0]["wrong_version_detected"] is True
