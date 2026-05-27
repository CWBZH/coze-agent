import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import Session.session_manager  # Import order avoids existing core/logger circular import in tests.
from Message.workflow.rag_types import RetrievalHit


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "acceptance" / "internal_backend_dry_run.py"
SOP_FIXTURE = REPO_ROOT / "docs" / "acceptance" / "fixtures" / "internal_sop_example.md"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("internal_backend_dry_run", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _run_cli(*args):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _run_json(*args):
    return json.loads(_run_cli(*args, "--json-only"))


def _run_json_allow_failure(*args):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--json-only"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    return completed.returncode, json.loads(completed.stdout)


def test_dry_run_does_not_execute_engine(monkeypatch, capsys):
    module = _load_script_module()

    class BombEngine:
        def __init__(self, *args, **kwargs):
            raise AssertionError("engine must not be constructed for --dry-run")

    monkeypatch.setattr(module, "InternalWorkflowEngine", BombEngine)

    exit_code = module.main(
        [
            "--shop-id",
            "shop-a",
            "--message",
            "do not execute this message",
            "--dry-run",
            "--json-only",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["action"] == "dry_run"
    assert output["content_length"] == len("do not execute this message")
    assert output["workflow_version"] == "internal-v1"
    assert output["sop_version"] is None
    assert output["knowledge_version"] is None
    assert output["sop_domains"] == []
    assert output["sop_record_count"] == 0


def test_dry_run_with_sop_file_summarizes_fixture_without_engine(monkeypatch, capsys):
    module = _load_script_module()

    class BombEngine:
        def __init__(self, *args, **kwargs):
            raise AssertionError("engine must not be constructed for --dry-run")

    monkeypatch.setattr(module, "InternalWorkflowEngine", BombEngine)

    exit_code = module.main(
        [
            "--shop-id",
            "shop-a",
            "--message",
            "do not execute this message",
            "--sop-file",
            str(SOP_FIXTURE),
            "--dry-run",
            "--json-only",
        ]
    )

    assert exit_code == 0
    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert output["dry_run"] is True
    assert output["workflow_version"] == "internal-v1"
    assert output["knowledge_version"] is None
    assert output["sop_record_count"] == 5
    assert output["sop_version"] == "sop-test-v1"
    assert "after_sales_evidence" in output["sop_domains"]
    assert "Please ask the buyer to provide clear photos" not in output_text


def test_json_only_outputs_valid_json():
    output = _run_json(
        "--shop-id",
        "shop-a",
        "--message",
        "\u6536\u5230\u7834\u635f\u4e86",
    )

    assert output["backend"] == "internal"
    assert output["message_type"] == "text"
    assert output["action"] == "request_evidence"
    assert output["workflow_version"] == "internal-v1"
    assert output["sop_version"] is None
    assert output["knowledge_version"] is None
    assert output["sop_domains"] == []
    assert output["sop_record_count"] == 0
    assert output["rag_enabled"] is False
    assert output["rag_hit_count"] == 0
    assert output["calls_llm"] is False


def test_fake_rag_dry_run_hits_without_echoing_content():
    private_hit_content = "private logistics content that must not be echoed"
    stdout = _run_cli(
        "--shop-id",
        "shop-a",
        "--message",
        "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
        "--use-fake-rag",
        "--rag-domain",
        "logistics_policy",
        "--rag-hit-title",
        "logistics title",
        "--rag-hit-content",
        private_hit_content,
        "--json-only",
    )
    output = json.loads(stdout)

    assert output["action"] == "reply"
    assert output["rag_enabled"] is True
    assert output["rag_status"] == "hit"
    assert output["rag_hit_count"] == 1
    assert output["rag_domains"] == ["logistics_policy"]
    assert output["retrieval_source"] == "in_memory"
    assert private_hit_content not in stdout


def test_fake_rag_e2e_profile_requires_hit_and_answer_generator():
    output = _run_json(
        "--shop-id",
        "synthetic-shop-1",
        "--message",
        "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
        "--use-fake-rag",
        "--rag-domain",
        "logistics_policy",
        "--rag-hit-title",
        "logistics title",
        "--rag-hit-content",
        "safe private logistics content",
        "--use-fake-answer-generator",
        "--rag-e2e-profile",
        "--require-rag-hit",
        "--expect-rag-domain",
        "logistics_policy",
        "--expect-answer-generator",
        "fake",
    )

    assert output["rag_e2e_profile"] is True
    assert output["rag_e2e_status"] == "ok"
    assert output["rag_requirement_status"] == "passed"
    assert output["answer_generation_status"] == "ok"
    assert output["answer_generator_required"] == "fake"
    assert output["guardrail_requirement_status"] == "not_required"


def test_fake_rag_e2e_profile_requires_version_and_source_type():
    output = _run_json(
        "--shop-id",
        "synthetic-shop-1",
        "--message",
        "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
        "--use-fake-rag",
        "--rag-domain",
        "logistics_policy",
        "--rag-version",
        "sop-test-v1",
        "--rag-hit-content",
        "safe private logistics content",
        "--use-fake-answer-generator",
        "--rag-e2e-profile",
        "--require-rag-hit",
        "--expect-rag-domain",
        "logistics_policy",
        "--expect-rag-version",
        "sop-test-v1",
        "--require-rag-version",
        "--expect-shop-id",
        "synthetic-shop-1",
        "--expect-rag-source-type",
        "synthetic_rag",
        "--expect-answer-generator",
        "fake",
    )

    assert output["rag_version_pinned"] is True
    assert output["rag_expected_version"] == "sop-test-v1"
    assert output["rag_version_status"] == "passed"
    assert output["rag_shop_status"] == "passed"
    assert output["rag_source_type_status"] == "passed"
    assert output["rag_hit_versions"] == ["sop-test-v1"]
    assert output["rag_hit_source_types"] == ["synthetic_rag"]


def test_fake_rag_e2e_profile_version_mismatch_fails():
    code, output = _run_json_allow_failure(
        "--shop-id",
        "synthetic-shop-1",
        "--message",
        "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
        "--use-fake-rag",
        "--rag-domain",
        "logistics_policy",
        "--rag-version",
        "sop-test-v1",
        "--use-fake-answer-generator",
        "--rag-e2e-profile",
        "--require-rag-hit",
        "--expect-rag-domain",
        "logistics_policy",
        "--expect-rag-version",
        "old-version",
        "--require-rag-version",
    )

    assert code == 1
    assert output["rag_e2e_status"] == "failed"
    assert output["rag_version_status"] == "failed_version_mismatch"


def test_fake_rag_e2e_profile_source_type_mismatch_fails():
    code, output = _run_json_allow_failure(
        "--shop-id",
        "synthetic-shop-1",
        "--message",
        "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
        "--use-fake-rag",
        "--rag-domain",
        "logistics_policy",
        "--rag-version",
        "sop-test-v1",
        "--use-fake-answer-generator",
        "--rag-e2e-profile",
        "--require-rag-hit",
        "--expect-rag-source-type",
        "sop",
    )

    assert code == 1
    assert output["rag_source_type_status"] == "failed_source_type_mismatch"


def test_fake_rag_e2e_profile_shop_mismatch_fails():
    code, output = _run_json_allow_failure(
        "--shop-id",
        "synthetic-shop-1",
        "--message",
        "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
        "--use-fake-rag",
        "--rag-domain",
        "logistics_policy",
        "--use-fake-answer-generator",
        "--rag-e2e-profile",
        "--require-rag-hit",
        "--expect-shop-id",
        "other-shop",
    )

    assert code == 1
    assert output["rag_shop_status"] == "failed_shop_mismatch"


def test_rag_e2e_profile_require_hit_fails_when_empty():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--shop-id",
            "synthetic-shop-1",
            "--message",
            "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
            "--rag-e2e-profile",
            "--require-rag-hit",
            "--expect-answer-generator",
            "fake",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 1
    output = json.loads(completed.stdout)
    assert output["rag_e2e_status"] == "failed"
    assert output["rag_requirement_status"] == "failed_no_hit"


def test_rag_e2e_profile_domain_mismatch_fails():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--shop-id",
            "synthetic-shop-1",
            "--message",
            "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
            "--use-fake-rag",
            "--rag-domain",
            "logistics_policy",
            "--rag-hit-content",
            "safe private logistics content",
            "--use-fake-answer-generator",
            "--rag-e2e-profile",
            "--require-rag-hit",
            "--expect-rag-domain",
            "after_sales_evidence",
            "--expect-answer-generator",
            "fake",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 1
    output = json.loads(completed.stdout)
    assert output["rag_e2e_status"] == "failed"
    assert output["rag_requirement_status"] == "failed_domain_mismatch"


def test_rag_e2e_dangerous_fake_answer_can_require_guardrail_block():
    output = _run_json(
        "--shop-id",
        "synthetic-shop-1",
        "--message",
        "Mini Balm \u591a\u5c11\u94b1",
        "--use-fake-rag",
        "--rag-domain",
        "product_catalog",
        "--rag-hit-content",
        "safe private product content",
        "--use-fake-answer-generator",
        "--fake-answer-dangerous",
        "--rag-e2e-profile",
        "--require-rag-hit",
        "--expect-rag-domain",
        "product_catalog",
        "--expect-answer-generator",
        "fake",
        "--expect-guardrail-status",
        "blocked",
    )

    assert output["rag_e2e_status"] == "ok"
    assert output["guardrail_status"] == "blocked"
    assert output["guardrail_requirement_status"] == "passed"
    assert output["action"] == "transfer_human"


def test_rag_e2e_pending_human_does_not_call_rag():
    output = _run_json(
        "--shop-id",
        "synthetic-shop-1",
        "--buyer-id",
        "buyer-a",
        "--session-id",
        "session-a",
        "--message",
        "Mini Balm \u591a\u5c11\u94b1",
        "--use-fake-rag",
        "--rag-domain",
        "product_catalog",
        "--use-fake-answer-generator",
        "--pending-human",
        "--rag-e2e-profile",
    )

    assert output["action"] == "transfer_human"
    assert output["intent"] == "pending_human_lock"
    assert output["rag_hit_count"] == 0
    assert output["rag_e2e_status"] == "ok"


def test_rag_e2e_redline_does_not_call_rag():
    output = _run_json(
        "--shop-id",
        "synthetic-shop-1",
        "--message",
        "\u4f60\u4eec\u662f\u5047\u8d27\u5427",
        "--use-fake-rag",
        "--rag-domain",
        "product_catalog",
        "--use-fake-answer-generator",
        "--rag-e2e-profile",
    )

    assert output["action"] == "transfer_human"
    assert output["intent"] == "human_escalation_redline"
    assert output["rag_hit_count"] == 0
    assert output["rag_e2e_status"] == "ok"


def test_real_rag_requires_explicit_pg_dsn():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--shop-id",
            "shop-a",
            "--message",
            "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
            "--rag-enabled",
            "--use-real-rag",
            "--ollama-base-url",
            "http://localhost:11434",
            "--embedding-model",
            "bge-m3",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 2
    assert "--pg-dsn" in completed.stderr


def test_real_rag_requires_explicit_ollama_base_url():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--shop-id",
            "shop-a",
            "--message",
            "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
            "--rag-enabled",
            "--use-real-rag",
            "--pg-dsn",
            "pgvector-dsn-private-password",
            "--embedding-model",
            "bge-m3",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 2
    assert "--ollama-base-url" in completed.stderr
    assert "private-password" not in completed.stderr


def test_real_rag_requires_explicit_embedding_model():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--shop-id",
            "shop-a",
            "--message",
            "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
            "--rag-enabled",
            "--use-real-rag",
            "--pg-dsn",
            "pgvector-dsn-private-password",
            "--ollama-base-url",
            "http://localhost:11434",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 2
    assert "--embedding-model" in completed.stderr
    assert "private-password" not in completed.stderr


def test_real_rag_construct_path_can_be_injected_without_external_calls(monkeypatch, capsys):
    module = _load_script_module()
    constructed = {"embedding": False, "store": False, "retriever": False}

    class FakeEmbeddingClient:
        def __init__(self, *, base_url, model):
            constructed["embedding"] = True
            assert base_url == "http://localhost:11434"
            assert model == "bge-m3"

    class FakePgVectorStore:
        def __init__(self, dsn):
            constructed["store"] = True
            assert "private-password" in dsn

    class FakeVectorStoreRAGRetriever:
        def __init__(self, *, embedding_client, vector_store, top_k):
            constructed["retriever"] = True
            self._last_stats = {
                "rag_status": "hit",
                "rag_hit_count": 1,
                "rag_domains": ["logistics_policy"],
                "rag_top_score": 0.88,
                "vector_store": "pgvector",
                "embedding_model": "bge-m3",
                "retrieval_source": "pgvector",
            }

        def retrieve(self, context, intent, domain, query, top_k=3):
            return [
                RetrievalHit(
                    chunk_id="real-rag-test",
                    shop_id=context.shop_id,
                    domain=domain,
                    title="masked logistics policy",
                    content_summary="safe summary",
                    score=0.88,
                    source_type="sop",
                    source_id="masked-source",
                    version="rag-v1",
                    content_hash="hash-rag",
                )
            ]

        def get_last_stats(self):
            return dict(self._last_stats)

    monkeypatch.setattr(module, "OllamaBgeM3EmbeddingClient", FakeEmbeddingClient)
    monkeypatch.setattr(module, "PgVectorStore", FakePgVectorStore)
    monkeypatch.setattr(module, "VectorStoreRAGRetriever", FakeVectorStoreRAGRetriever)

    exit_code = module.main(
        [
            "--shop-id",
            "shop-a",
            "--message",
            "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
            "--rag-enabled",
            "--use-real-rag",
            "--pg-dsn",
            "pgvector-dsn-private-password",
            "--ollama-base-url",
            "http://localhost:11434",
            "--embedding-model",
            "bge-m3",
            "--rag-domain",
            "logistics_policy",
            "--use-fake-answer-generator",
            "--json-only",
        ]
    )

    assert exit_code == 0
    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert constructed == {"embedding": True, "store": True, "retriever": True}
    assert output["rag_enabled"] is True
    assert output["rag_status"] == "hit"
    assert output["rag_hit_count"] == 1
    assert output["vector_store"] == "pgvector"
    assert output["embedding_model"] == "bge-m3"
    assert output["calls_ollama"] is True
    assert output["connects_pgvector"] is True
    assert "private-password" not in output_text


def test_json_only_with_sop_file_outputs_valid_json():
    output = _run_json(
        "--shop-id",
        "shop-a",
        "--message",
        "\u6536\u5230\u7834\u635f\u4e86",
        "--sop-file",
        str(SOP_FIXTURE),
    )

    assert output["action"] == "request_evidence"
    assert output["sop_record_count"] == 5
    assert output["sop_domains"] == [
        "after_sales_evidence",
        "logistics_policy",
        "promotion_policy",
        "redline_escalation",
        "sensitive_user_safety",
    ]


def test_fake_product_product_basic_gets_knowledge_hit():
    output = _run_json(
        "--shop-id",
        "shop-a",
        "--message",
        "Mini Balm \u591a\u5c11\u94b1",
        "--fake-product",
    )

    assert output["action"] == "reply"
    assert output["intent"] == "product_basic"
    assert output["workflow_version"] == "internal-v1"
    assert output["knowledge_version"] == "product_repository"
    assert output["knowledge_hit_count"] >= 1
    assert output["knowledge_source"] == "repository"
    assert output["product_cache_hit"] is False


def test_redline_problem_transfers_human():
    output = _run_json(
        "--shop-id",
        "shop-a",
        "--message",
        "\u4f60\u4eec\u662f\u5047\u8d27\u5427",
    )

    assert output["action"] == "transfer_human"
    assert output["intent"] == "human_escalation_redline"
    assert "redline" in output["risk_flags"]


def test_after_sales_problem_requests_evidence():
    output = _run_json(
        "--shop-id",
        "shop-a",
        "--message",
        "\u6536\u5230\u7834\u635f\u4e86",
    )

    assert output["action"] == "request_evidence"
    assert output["intent"] == "after_sales_evidence_collection"
    assert "needs_evidence" in output["risk_flags"]


def test_with_fake_history_outputs_hashed_history_summary_only():
    stdout = _run_cli(
        "--shop-id",
        "shop-a",
        "--buyer-id",
        "buyer-a",
        "--session-id",
        "session-a",
        "--message",
        "\u6536\u5230\u7834\u635f\u4e86",
        "--with-fake-history",
        "--json-only",
    )
    output = json.loads(stdout)

    assert output["history_message_count"] == 1
    assert output["history_window_size"] == 1
    assert output["pending_human"] is False
    assert output["conversation_id_hash"]
    assert "synthetic history buyer message" not in stdout


def test_pending_human_dry_run_transfers_without_product_reply():
    output = _run_json(
        "--shop-id",
        "shop-a",
        "--buyer-id",
        "buyer-a",
        "--session-id",
        "session-a",
        "--message",
        "Mini Balm \u591a\u5c11\u94b1",
        "--fake-product",
        "--pending-human",
    )

    assert output["action"] == "transfer_human"
    assert output["intent"] == "pending_human_lock"
    assert output["reason"] == "pending_human_conversation"
    assert output["pending_human"] is True
    assert output["history_message_count"] == 1
    assert output["knowledge_hit_count"] == 0


def test_fake_answer_generator_outputs_metadata_only():
    output = _run_json(
        "--shop-id",
        "synthetic-shop-1",
        "--message",
        "Mini Balm \u591a\u5c11\u94b1",
        "--fake-product",
        "--use-fake-answer-generator",
    )

    assert output["answer_generator"] == "fake"
    assert output["answer_generation_source"] == "fake"
    assert output["answer_generation_status"] == "ok"
    assert output["answer_confidence"] > 0
    assert output["answer_length"] > 0
    assert output["answer_hash"]
    assert output["calls_llm"] is False
    assert output["prompt_hash"]
    assert "reply_text" not in output


def test_real_answer_generator_requires_explicit_llm_args():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--shop-id",
            "synthetic-shop-1",
            "--message",
            "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
            "--use-real-answer-generator",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 2
    assert "--llm-base-url" in completed.stderr
    assert "--llm-model" in completed.stderr
    assert "AI_WORKFLOW_LLM_API_KEY=" not in completed.stderr


def test_real_answer_generator_construct_path_can_be_injected_without_external_calls(monkeypatch, capsys):
    module = _load_script_module()
    constructed = {"generator": False}

    class FakeOpenAICompatibleAnswerGenerator:
        def __init__(self, *, base_url, model, api_key_env, timeout_seconds):
            constructed["generator"] = True
            assert base_url == "https://llm.example.test/v1"
            assert model == "test-model"
            assert api_key_env == "AI_WORKFLOW_TEST_LLM_KEY"
            assert timeout_seconds == 3.0

        def generate(self, context):
            from Message.workflow.answer_generator import AnswerDraft

            return AnswerDraft(
                text="Safe generated answer. " * 20,
                confidence=0.91,
                source="openai_compatible",
                used_history_count=len(context.history_window),
            )

    monkeypatch.setattr(module, "OpenAICompatibleAnswerGenerator", FakeOpenAICompatibleAnswerGenerator)

    exit_code = module.main(
        [
            "--shop-id",
            "synthetic-shop-1",
            "--message",
            "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230",
            "--use-fake-rag",
            "--rag-domain",
            "logistics_policy",
            "--use-real-answer-generator",
            "--llm-base-url",
            "https://llm.example.test/v1",
            "--llm-model",
            "test-model",
            "--llm-api-key-env",
            "AI_WORKFLOW_TEST_LLM_KEY",
            "--llm-timeout-seconds",
            "3",
            "--require-answer-generated",
            "--expect-answer-generator",
            "openai_compatible",
            "--json-only",
        ]
    )

    assert exit_code == 0
    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert constructed["generator"] is True
    assert output["calls_llm"] is True
    assert output["answer_generator"] == "openai_compatible"
    assert output["answer_generation_status"] == "ok"
    assert output["answer_length"] > 160
    assert output["answer_hash"]
    assert len(output["answer_preview_truncated"]) <= 160
    assert "reply_text" not in output_text


def test_dangerous_fake_answer_generator_is_guardrailed():
    output = _run_json(
        "--shop-id",
        "synthetic-shop-1",
        "--message",
        "Mini Balm \u591a\u5c11\u94b1",
        "--fake-product",
        "--use-fake-answer-generator",
        "--fake-answer-dangerous",
    )

    assert output["answer_generator"] == "fake"
    assert output["action"] == "transfer_human"
    assert output["guardrail_status"] == "blocked"
    assert "policy_violation" in output["risk_flags"]


def test_multiple_history_messages_are_parsed_and_hidden():
    stdout = _run_cli(
        "--shop-id",
        "shop-a",
        "--buyer-id",
        "buyer-a",
        "--session-id",
        "session-a",
        "--message",
        "\u90a3\u600e\u4e48\u7528\uff1f",
        "--history-message",
        "buyer:\u8fd9\u4e2a\u6709\u4ec0\u4e48\u89c4\u683c",
        "--history-message",
        "seller:\u8fd9\u6b3e\u6709\u591a\u4e2a\u89c4\u683c",
        "--json-only",
    )
    output = json.loads(stdout)

    assert output["history_message_count"] == 2
    assert output["history_window_size"] == 2
    assert output["history_source"] == "memory"
    assert "\u8fd9\u4e2a\u6709\u4ec0\u4e48\u89c4\u683c" not in stdout
    assert "\u8fd9\u6b3e\u6709\u591a\u4e2a\u89c4\u683c" not in stdout


def test_invalid_history_role_returns_error():
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--shop-id",
            "shop-a",
            "--message",
            "hello",
            "--history-message",
            "badrole:private text",
            "--json-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode == 2
    assert "role buyer/seller/ai/system" in completed.stderr
    assert "private text" not in completed.stderr


def test_history_message_takes_precedence_over_conversation_db(tmp_path):
    missing_db = tmp_path / "missing.sqlite"
    stdout = _run_cli(
        "--shop-id",
        "shop-a",
        "--buyer-id",
        "buyer-a",
        "--session-id",
        "session-a",
        "--message",
        "\u6536\u5230\u7834\u635f\u4e86",
        "--history-message",
        "buyer:FAKE_HISTORY_WINS",
        "--use-conversation-db",
        "--conversation-db-path",
        str(missing_db),
        "--json-only",
    )
    output = json.loads(stdout)

    assert output["history_source"] == "memory"
    assert output["history_message_count"] == 1
    assert "FAKE_HISTORY_WINS" not in stdout


def test_use_db_missing_db_does_not_crash(tmp_path):
    missing_db = tmp_path / "missing.sqlite"

    output = _run_json(
        "--shop-id",
        "shop-a",
        "--message",
        "Mini Balm \u591a\u5c11\u94b1",
        "--use-db",
        "--db-path",
        str(missing_db),
    )

    assert output["backend"] == "internal"
    assert output["intent"] == "ask_product_clarification"
    assert output["knowledge_hit_count"] == 0


def test_use_conversation_db_missing_db_does_not_crash(tmp_path):
    missing_db = tmp_path / "missing-conversation.sqlite"

    output = _run_json(
        "--shop-id",
        "shop-a",
        "--buyer-id",
        "buyer-a",
        "--session-id",
        "session-a",
        "--message",
        "Mini Balm \u591a\u5c11\u94b1",
        "--use-conversation-db",
        "--conversation-db-path",
        str(missing_db),
    )

    assert output["backend"] == "internal"
    assert output["history_message_count"] == 0
    assert output["history_source"] == "sqlite_missing"


def test_use_conversation_db_outputs_history_summary_without_raw_content(tmp_path):
    db_path = tmp_path / "conversation.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE conversations (id TEXT PRIMARY KEY, shop_id TEXT, user_id TEXT, buyer_id TEXT, session_id TEXT, pending_human INTEGER)"
    )
    conn.execute(
        "CREATE TABLE messages (conversation_id TEXT, role TEXT, message_type TEXT, content TEXT, created_at TEXT, source TEXT)"
    )
    conn.execute(
        "INSERT INTO conversations (id, shop_id, user_id, buyer_id, session_id, pending_human) VALUES (?, ?, ?, ?, ?, ?)",
        ("conv-a", "shop-a", "user-a", "buyer-a", "session-a", 0),
    )
    conn.execute(
        "INSERT INTO messages (conversation_id, role, message_type, content, created_at, source) VALUES (?, ?, ?, ?, ?, ?)",
        ("conv-a", "buyer", "text", "PRIVATE_SQLITE_HISTORY", "2026-05-21T01:00:00Z", "sqlite_test"),
    )
    conn.commit()
    conn.close()

    stdout = _run_cli(
        "--shop-id",
        "shop-a",
        "--user-id",
        "user-a",
        "--buyer-id",
        "buyer-a",
        "--session-id",
        "session-a",
        "--message",
        "\u6536\u5230\u7834\u635f\u4e86",
        "--use-conversation-db",
        "--conversation-db-path",
        str(db_path),
        "--json-only",
    )
    output = json.loads(stdout)

    assert output["history_message_count"] == 1
    assert output["history_window_size"] == 1
    assert output["history_source"] == "sqlite"
    assert "PRIVATE_SQLITE_HISTORY" not in stdout


def test_malformed_sop_file_does_not_crash(tmp_path):
    malformed = tmp_path / "bad_sop.md"
    malformed.write_text("## Bad SOP\nnot a valid field line\n", encoding="utf-8")

    output = _run_json(
        "--shop-id",
        "shop-a",
        "--message",
        "\u6536\u5230\u7834\u635f\u4e86",
        "--sop-file",
        str(malformed),
    )

    assert output["backend"] == "internal"
    assert output["sop_record_count"] == 0
    assert output["sop_domains"] == []
    assert output["sop_error_count"] >= 1


def test_output_omits_full_message_reply_and_product_details():
    full_message = "SECRET_FULL_MESSAGE_should_not_be_printed"
    stdout = _run_cli(
        "--shop-id",
        "shop-a",
        "--message",
        full_message,
        "--fake-product",
        "--json-only",
    )

    assert full_message not in stdout
    assert "Compact fake product detail that must stay private" not in stdout
    assert "reply_text" not in stdout
    assert '"content"' not in stdout


def test_output_omits_full_sop_body():
    stdout = _run_cli(
        "--shop-id",
        "shop-a",
        "--message",
        "\u6536\u5230\u7834\u635f\u4e86",
        "--sop-file",
        str(SOP_FIXTURE),
        "--json-only",
    )

    assert "Please ask the buyer to provide clear photos" not in stdout
    assert "Do not approve refunds before evidence" not in stdout
    assert "sop-after-sales-001" not in stdout
