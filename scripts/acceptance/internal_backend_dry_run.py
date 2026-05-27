"""No-send dry-run helper for the internal workflow backend.

This script is for manual acceptance checks of InternalWorkflowEngine only. It
does not import channel senders, FastGPT clients, queue workers, or runtime
message send paths.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import Session.session_manager  # Import order avoids existing core/logger circular import.
from Message.workflow.internal_engine import (
    INTERNAL_WORKFLOW_VERSION,
    InternalWorkflowEngine,
)
from Message.workflow.answer_generator import FakeAnswerGenerator, OpenAICompatibleAnswerGenerator
from Message.workflow.llm_classifier import OpenAICompatibleIntentClassifier
from Message.workflow.conversation_context import (
    ConversationRecord,
    InMemoryConversationContextRepository,
    SQLiteConversationContextRepository,
)
from Message.workflow.knowledge_repository import ProductKnowledgeRepository
from Message.workflow.embedding_client import OllamaBgeM3EmbeddingClient
from Message.workflow.rag_retriever import InMemoryRAGRetriever, VectorStoreRAGRetriever
from Message.workflow.rag_types import KnowledgeChunk
from Message.workflow.sop_provider import SOPProvider
from Message.workflow.types import WorkflowContext, WorkflowResult, action_value
from Message.workflow.vector_store import PgVectorStore
from scripts.acceptance.internal_engine_cases import load_sop_fixture_summary


FAKE_GOODS_NAME = "Mini Balm"
FAKE_PRIVATE_DETAIL = "Compact fake product detail that must stay private"
SOP_DOMAINS = {
    "after_sales_evidence",
    "logistics_policy",
    "promotion_policy",
    "redline_escalation",
    "sensitive_user_safety",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run InternalWorkflowEngine in a no-send, no-write dry-run mode."
    )
    parser.add_argument("--shop-id", required=True, help="Platform shop id.")
    parser.add_argument("--user-id", default="", help="Optional platform user id.")
    parser.add_argument("--buyer-id", default="", help="Optional buyer id.")
    parser.add_argument("--session-id", default="", help="Optional session id.")
    parser.add_argument("--message", required=True, help="Buyer message content. Never echoed in output.")
    parser.add_argument("--message-type", default="text", help="Message type. Defaults to text.")
    parser.add_argument("--goods-id", default="", help="Optional product goods_id for internal product context.")
    parser.add_argument("--goods-name", default="", help="Optional product name for internal product context.")
    parser.add_argument("--goods-price", default="", help="Optional product price for internal product context.")
    parser.add_argument("--goods-spec", default="", help="Optional product spec for internal product context.")
    parser.add_argument("--db-path", type=Path, help="SQLite DB path for --use-db.")
    parser.add_argument("--use-db", action="store_true", help="Use a read-only SQLite product repository.")
    parser.add_argument("--fake-product", action="store_true", help="Use short fake product records.")
    parser.add_argument("--sop-file", type=Path, help="Optional reviewed SOP Markdown fixture to summarize.")
    parser.add_argument(
        "--history-message",
        action="append",
        default=[],
        help="Synthetic history item as role:text. Role must be buyer, seller, ai, or system.",
    )
    parser.add_argument("--with-fake-history", action="store_true", help="Attach synthetic hashed history.")
    parser.add_argument("--pending-human", action="store_true", help="Attach synthetic pending-human history.")
    parser.add_argument("--use-conversation-db", action="store_true", help="Use read-only SQLite conversation history.")
    parser.add_argument("--conversation-db-path", type=Path, help="SQLite DB path for --use-conversation-db.")
    parser.add_argument("--conversation-session-id", default="", help="Override session id for conversation DB lookup.")
    parser.add_argument("--conversation-buyer-id", default="", help="Override buyer id for conversation DB lookup.")
    parser.add_argument("--json-only", action="store_true", help="Print only JSON summary.")
    parser.add_argument("--dry-run", action="store_true", help="Only print context summary; do not execute engine.")
    parser.add_argument("--use-fake-answer-generator", action="store_true", help="Use offline fake answer generator.")
    parser.add_argument("--fake-answer-style", default="conservative", help="Fake answer generator style.")
    parser.add_argument("--fake-answer-dangerous", action="store_true", help="Emit a risky fake draft for guardrail tests.")
    parser.add_argument("--use-real-answer-generator", action="store_true", help="Use explicit OpenAI-compatible answer generator.")
    parser.add_argument("--use-real-intent-classifier", action="store_true", help="Use explicit OpenAI-compatible intent classifier.")
    parser.add_argument("--llm-base-url", default="", help="OpenAI-compatible base URL for --use-real-answer-generator.")
    parser.add_argument("--llm-model", default="", help="OpenAI-compatible model for --use-real-answer-generator.")
    parser.add_argument("--llm-api-key-env", default="AI_WORKFLOW_LLM_API_KEY", help="Environment variable containing the LLM API key.")
    parser.add_argument("--llm-timeout-seconds", type=float, default=20.0, help="LLM request timeout.")
    parser.add_argument("--answer-preview-max-chars", type=int, default=160, help="Maximum metadata-only answer preview length.")
    parser.add_argument("--show-reply", action="store_true", help="Include final reply text in stdout for manual no-send testing.")
    parser.add_argument("--require-answer-generated", action="store_true", help="Fail if no answer draft is generated.")
    parser.add_argument("--rag-enabled", action="store_true", help="Mark RAG as enabled without injecting external services.")
    parser.add_argument("--use-fake-rag", action="store_true", help="Use offline in-memory RAG hits.")
    parser.add_argument("--use-real-rag", action="store_true", help="Use explicit pgvector + Ollama RAG retriever.")
    parser.add_argument("--pg-dsn", default="", help="PostgreSQL/pgvector DSN for --use-real-rag.")
    parser.add_argument("--ollama-base-url", default="", help="Ollama base URL for --use-real-rag.")
    parser.add_argument("--embedding-model", default="", help="Embedding model for --use-real-rag.")
    parser.add_argument("--rag-domain", default="logistics_policy", help="Domain for --use-fake-rag hit.")
    parser.add_argument("--rag-version", default="", help="Optional RAG retrieval version pin.")
    parser.add_argument("--product-version", default="", help="Product RAG version pin for product domains.")
    parser.add_argument("--sop-version", default="", help="SOP RAG version pin for non-product domains.")
    parser.add_argument("--rag-top-k", type=int, default=3, help="RAG retrieval limit.")
    parser.add_argument("--rag-hit-title", default="synthetic RAG hit", help="Short fake RAG hit title.")
    parser.add_argument("--rag-hit-content", default="synthetic safe RAG content", help="Fake RAG hit content. Not echoed.")
    parser.add_argument("--rag-e2e-profile", action="store_true", help="Run no-send RAG answer-generation acceptance checks.")
    parser.add_argument("--require-rag-hit", action="store_true", help="Fail the profile if no RAG hit is returned.")
    parser.add_argument("--expect-rag-domain", default="", help="Expected RAG domain for profile checks.")
    parser.add_argument("--expect-rag-version", default="", help="Expected RAG hit version for profile checks.")
    parser.add_argument("--require-rag-version", action="store_true", help="Fail the profile if RAG hit version is missing or mismatched.")
    parser.add_argument("--expect-shop-id", default="", help="Expected raw shop id; only its hash is compared.")
    parser.add_argument("--expect-rag-source-type", default="", help="Expected RAG hit source_type.")
    parser.add_argument("--expect-rag-content-hash", default="", help="Expected RAG hit content_hash.")
    parser.add_argument("--expect-answer-generator", default="", help="Expected answer generator name for profile checks.")
    parser.add_argument("--expect-guardrail-status", default="", help="Expected guardrail status for profile checks.")
    return parser.parse_args(argv)


def build_context(args: argparse.Namespace) -> WorkflowContext:
    use_fake_generator = bool(getattr(args, "use_fake_answer_generator", False))
    goods_context = _goods_context_from_args(args)
    if not goods_context and (args.fake_product or use_fake_generator):
        goods_context = {"goods_name": FAKE_GOODS_NAME, "goods_id": "fake-mini-balm"}
    buyer_id = str(getattr(args, "conversation_buyer_id", "") or args.buyer_id or "")
    session_id = str(getattr(args, "conversation_session_id", "") or args.session_id or "")
    return WorkflowContext(
        trace_id=f"internal-dry-run-{_short_hash(args.shop_id + ':' + args.message)}",
        shop_id=str(args.shop_id or ""),
        user_id=str(args.user_id or ""),
        customer_uid=buyer_id,
        buyer_id=buyer_id,
        session_id=session_id,
        chat_id=session_id,
        message_type=str(args.message_type or "text"),
        content=str(args.message or ""),
        goods_context=goods_context,
        metadata={
            "source": "internal_backend_dry_run",
            "no_send": True,
            "no_db_write": True,
            "fake_product": bool(args.fake_product),
            "use_db": bool(args.use_db),
            "goods_id": str(getattr(args, "goods_id", "") or ""),
            "goods_name": str(getattr(args, "goods_name", "") or ""),
            "product_version": str(getattr(args, "product_version", "") or ""),
            "sop_version": str(getattr(args, "sop_version", "") or ""),
            **load_sop_fixture_summary(args.sop_file),
        },
    )


def _goods_context_from_args(args: argparse.Namespace) -> dict[str, str]:
    fields = {
        "goods_id": str(getattr(args, "goods_id", "") or ""),
        "goods_name": str(getattr(args, "goods_name", "") or ""),
        "goods_price": str(getattr(args, "goods_price", "") or ""),
        "spec": str(getattr(args, "goods_spec", "") or ""),
    }
    return {key: value for key, value in fields.items() if value}


def build_engine(args: argparse.Namespace) -> InternalWorkflowEngine:
    repository = build_repository(args)
    sop_provider = SOPProvider.from_markdown_file(args.sop_file) if args.sop_file else None
    return InternalWorkflowEngine(
        knowledge_repository=repository,
        intent_classifier=build_intent_classifier(args),
        sop_provider=sop_provider,
        conversation_context_repository=build_conversation_repository(args),
        answer_generator=build_answer_generator(args),
        rag_retriever=build_rag_retriever(args),
    )


def build_intent_classifier(args: argparse.Namespace):
    if not bool(getattr(args, "use_real_intent_classifier", False)):
        return None
    _validate_real_answer_args(args, flag_name="--use-real-intent-classifier")
    return OpenAICompatibleIntentClassifier(
        base_url=str(getattr(args, "llm_base_url", "") or ""),
        model=str(getattr(args, "llm_model", "") or ""),
        api_key_env=str(getattr(args, "llm_api_key_env", "") or "AI_WORKFLOW_LLM_API_KEY"),
        timeout_seconds=float(getattr(args, "llm_timeout_seconds", 20.0) or 20.0),
    )


def build_answer_generator(args: argparse.Namespace):
    if bool(getattr(args, "use_real_answer_generator", False)):
        _validate_real_answer_args(args, flag_name="--use-real-answer-generator")
        return OpenAICompatibleAnswerGenerator(
            base_url=str(getattr(args, "llm_base_url", "") or ""),
            model=str(getattr(args, "llm_model", "") or ""),
            api_key_env=str(getattr(args, "llm_api_key_env", "") or "AI_WORKFLOW_LLM_API_KEY"),
            timeout_seconds=float(getattr(args, "llm_timeout_seconds", 20.0) or 20.0),
        )
    if not bool(
        getattr(args, "use_fake_answer_generator", False)
        or getattr(args, "show_reply", False)
        or getattr(args, "use_fake_rag", False)
        or getattr(args, "fake_product", False)
    ):
        return None
    return FakeAnswerGenerator(
        style=str(getattr(args, "fake_answer_style", "") or "conservative"),
        dangerous=bool(getattr(args, "fake_answer_dangerous", False)),
    )


def build_rag_retriever(args: argparse.Namespace):
    if bool(getattr(args, "use_real_rag", False)):
        _validate_real_rag_args(args)
        kwargs = {
            "embedding_client": OllamaBgeM3EmbeddingClient(
                base_url=str(getattr(args, "ollama_base_url", "") or ""),
                model=str(getattr(args, "embedding_model", "") or ""),
            ),
            "vector_store": PgVectorStore(str(getattr(args, "pg_dsn", "") or "")),
            "top_k": max(1, int(getattr(args, "rag_top_k", 3) or 3)),
        }
        version = str(
            getattr(args, "rag_version", "")
            or getattr(args, "product_version", "")
            or getattr(args, "sop_version", "")
            or ""
        )
        if version:
            try:
                return VectorStoreRAGRetriever(**kwargs, version=version)
            except TypeError:
                return VectorStoreRAGRetriever(**kwargs)
        return VectorStoreRAGRetriever(**kwargs)
    if not bool(getattr(args, "use_fake_rag", False) or getattr(args, "show_reply", False)):
        return None
    if bool(getattr(args, "show_reply", False)) and not bool(getattr(args, "use_fake_rag", False)):
        version = str(getattr(args, "rag_version", "") or getattr(args, "product_version", "") or "fake-rag-v1")
        chunks = [
            KnowledgeChunk(
                chunk_id=f"dry-run-{domain}",
                shop_id=str(args.shop_id or ""),
                domain=domain,
                source_type="product" if domain == "product_catalog" else "sop",
                source_id=f"dry-run-{domain}",
                title=f"{domain} safe fixture",
                content=_fake_rag_content(domain, args),
                version=version if domain == "product_catalog" else str(getattr(args, "sop_version", "") or version),
            )
            for domain in ("product_catalog", "logistics_policy", "after_sales_evidence", "promotion_policy", "sensitive_user_safety")
        ]
        return InMemoryRAGRetriever(chunks, version="", top_k=max(1, int(getattr(args, "rag_top_k", 3) or 3)))
    domain = str(getattr(args, "rag_domain", "") or "logistics_policy")
    version = str(getattr(args, "rag_version", "") or getattr(args, "expect_rag_version", "") or "rag-dry-run-v1")
    return InMemoryRAGRetriever(
        [
            KnowledgeChunk(
                chunk_id=f"dry-run-{_short_hash(str(args.shop_id) + ':' + domain)}",
                shop_id=str(args.shop_id or ""),
                domain=domain,
                source_type=str(getattr(args, "rag_hit_source_type", "") or "synthetic_rag"),
                source_id="dry-run-rag-hit",
                title=str(getattr(args, "rag_hit_title", "") or "synthetic RAG hit"),
                content=str(getattr(args, "rag_hit_content", "") or "synthetic safe RAG content"),
                version=version,
            )
        ],
        version=str(getattr(args, "rag_version", "") or getattr(args, "expect_rag_version", "") or ""),
        top_k=max(1, int(getattr(args, "rag_top_k", 3) or 3)),
    )


def _fake_rag_content(domain: str, args: argparse.Namespace) -> str:
    if domain == "product_catalog":
        return (
            f"商品名称: {getattr(args, 'goods_name', '') or FAKE_GOODS_NAME}\n"
            "价格边界: 价格以商品页面和结算页显示为准。\n"
            "用法: 按商品页面说明使用。"
        )
    if domain == "logistics_policy":
        return "物流以订单物流页为准；客服不编造具体物流状态，可转人工核实。"
    if domain == "after_sales_evidence":
        return "售后问题需收集商品照片、外包装照片、订单信息和问题描述，不承诺退款补发赔偿。"
    if domain == "promotion_policy":
        return "优惠以商品页面、活动页和结算页为准，不承诺私下优惠、赠品或返差价。"
    if domain == "sensitive_user_safety":
        return "孕妇、儿童、过敏、敏感肌等需查看成分和说明，必要时咨询专业人士或转人工。"
    return "安全客服知识片段。"


def _validate_real_rag_args(args: argparse.Namespace) -> None:
    missing = []
    if not str(getattr(args, "pg_dsn", "") or "").strip():
        missing.append("--pg-dsn")
    if not str(getattr(args, "ollama_base_url", "") or "").strip():
        missing.append("--ollama-base-url")
    if not str(getattr(args, "embedding_model", "") or "").strip():
        missing.append("--embedding-model")
    if missing:
        raise ValueError("--use-real-rag requires " + ", ".join(missing))


def _validate_real_answer_args(args: argparse.Namespace, *, flag_name: str = "--use-real-answer-generator") -> None:
    missing = []
    if not str(getattr(args, "llm_base_url", "") or "").strip():
        missing.append("--llm-base-url")
    if not str(getattr(args, "llm_model", "") or "").strip():
        missing.append("--llm-model")
    if not str(getattr(args, "llm_api_key_env", "") or "").strip():
        missing.append("--llm-api-key-env")
    if missing:
        raise ValueError(f"{flag_name} requires " + ", ".join(missing))


def build_conversation_repository(args: argparse.Namespace):
    with_fake_history = bool(getattr(args, "with_fake_history", False))
    pending_human = bool(getattr(args, "pending_human", False))
    history_messages = _parse_history_messages(getattr(args, "history_message", []) or [])
    if history_messages:
        return InMemoryConversationContextRepository(
            _history_records_from_messages(args, history_messages, pending_human=pending_human)
        )
    use_conversation_db = bool(getattr(args, "use_conversation_db", False))
    if use_conversation_db:
        db_path = getattr(args, "conversation_db_path", None)
        return SQLiteConversationContextRepository(db_path or "temp/channel_shop.db")
    if not with_fake_history and not pending_human:
        return None
    buyer_id = str(getattr(args, "conversation_buyer_id", "") or args.buyer_id or "")
    session_id = str(getattr(args, "conversation_session_id", "") or args.session_id or "")
    records = [
        ConversationRecord(
            shop_id=str(args.shop_id or ""),
            user_id=str(args.user_id or ""),
            buyer_id=buyer_id,
            session_id=session_id,
            role="buyer",
            message_type="text",
            content="synthetic history buyer message",
            created_at="2026-05-21T01:00:00Z",
            source="synthetic_dry_run",
            human_state="pending_human" if pending_human else "",
            pending_human=pending_human,
            intent="after_sales_evidence_collection" if pending_human else "product_basic",
            action="transfer_human" if pending_human else "reply",
        )
    ]
    return InMemoryConversationContextRepository(records)


def _history_records_from_messages(
    args: argparse.Namespace,
    messages: list[tuple[str, str]],
    *,
    pending_human: bool,
) -> list[ConversationRecord]:
    buyer_id = str(getattr(args, "conversation_buyer_id", "") or args.buyer_id or "")
    session_id = str(getattr(args, "conversation_session_id", "") or args.session_id or "")
    records = []
    for index, (role, content) in enumerate(messages):
        records.append(
            ConversationRecord(
                shop_id=str(args.shop_id or ""),
                user_id=str(args.user_id or ""),
                buyer_id=buyer_id,
                session_id=session_id,
                role=role,
                message_type="text",
                content=content,
                created_at=f"2026-05-21T01:00:{index:02d}Z",
                source="synthetic_history_message",
                human_state="pending_human" if pending_human else "",
                pending_human=pending_human,
                intent="pending_human_lock" if pending_human else "",
                action="transfer_human" if pending_human else "",
            )
        )
    return records


def _parse_history_messages(values: list[str]) -> list[tuple[str, str]]:
    allowed_roles = {"buyer", "seller", "ai", "system"}
    parsed = []
    for value in values:
        role, sep, content = str(value or "").partition(":")
        role = role.strip().lower()
        if not sep or role not in allowed_roles:
            raise ValueError("--history-message must use role:text with role buyer/seller/ai/system")
        parsed.append((role, content))
    return parsed


def build_repository(args: argparse.Namespace) -> ProductKnowledgeRepository:
    if args.fake_product or bool(getattr(args, "use_fake_answer_generator", False)):
        return ProductKnowledgeRepository(
            records_source=lambda shop_id: fake_product_records(shop_id),
            ttl_seconds=300,
        )
    if args.use_db:
        session_provider = build_readonly_session_provider(args.db_path)
        if session_provider is not None:
            return ProductKnowledgeRepository(session_provider=session_provider, ttl_seconds=300)
    return ProductKnowledgeRepository(records_source=[], ttl_seconds=300)


def build_readonly_session_provider(db_path: Path | None):
    resolved = _resolve_db_path(db_path)
    if resolved is None or not resolved.exists():
        return None

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    sqlite_uri = f"sqlite:///file:{resolved.as_posix()}?mode=ro&uri=true"
    engine = create_engine(sqlite_uri)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return session_factory


def _resolve_db_path(db_path: Path | None) -> Path | None:
    if db_path is not None:
        return db_path.expanduser().resolve()
    try:
        from core import settings

        return settings.db_path().resolve()
    except Exception:
        return None


def fake_product_records(shop_id: str) -> list[dict[str, Any]]:
    return [
        {
            "shop_id": str(shop_id or ""),
            "domain": "product_catalog",
            "source": "fake_product_record",
            "goods_id": "fake-mini-balm",
            "goods_name": FAKE_GOODS_NAME,
            "price": "19.90",
            "specifications": "15g",
            "usage_method": "Apply a small amount to dry areas.",
            "ingredients": "Shea butter, glycerin",
            "shelf_life": "24 months",
            "warnings": "Patch test before use.",
            "manual_notes": FAKE_PRIVATE_DETAIL,
        }
    ]


async def run_engine(args: argparse.Namespace) -> WorkflowResult:
    engine = build_engine(args)
    return await engine.run(build_context(args))


def dry_run_summary(args: argparse.Namespace) -> dict[str, Any]:
    summary = {
        **base_summary(args),
        "dry_run": True,
        "action": "dry_run",
        "intent": "",
        "reason": "engine_not_executed",
        "risk_flags": [],
        "knowledge_version": None,
        "knowledge_hit_count": 0,
        "knowledge_source": "not_executed",
        "answer_generator": "not_executed",
        "answer_generation_source": "",
        "answer_generation_status": "not_executed",
        "answer_confidence": 0.0,
        "answer_length": 0,
        "answer_hash": "",
        "answer_preview_truncated": "",
        "used_history_count": 0,
        "used_rag_hit_count": 0,
        "prompt_hash": "",
        "calls_llm": bool(getattr(args, "use_real_answer_generator", False) or getattr(args, "use_real_intent_classifier", False)),
        "product_cache_hit": None,
        "product_cache_ttl_seconds": None,
        "rag_enabled": bool(getattr(args, "rag_enabled", False) or getattr(args, "use_fake_rag", False) or getattr(args, "use_real_rag", False)),
        "rag_status": "not_executed" if getattr(args, "rag_enabled", False) or getattr(args, "use_fake_rag", False) or getattr(args, "use_real_rag", False) else "disabled",
        "rag_hit_count": 0,
        "rag_domains": [],
        "rag_top_score": 0.0,
        "rag_version_pinned": bool(getattr(args, "rag_version", "")),
        "rag_expected_version": str(getattr(args, "expect_rag_version", "") or ""),
        "rag_hit_versions": [],
        "rag_version_status": "not_required",
        "rag_shop_status": "not_required",
        "rag_source_type_status": "not_required",
        "rag_hit_content_hashes": [],
        "rag_hit_source_types": [],
        "rag_hit_source_ids_hash": [],
        "rag_hit_shop_ids_hash": [],
        "vector_store": "",
        "embedding_model": "",
        "retrieval_source": "",
        "calls_ollama": bool(getattr(args, "use_real_rag", False)),
        "connects_pgvector": bool(getattr(args, "use_real_rag", False)),
    }
    return _attach_rag_e2e_profile(args, summary)


def result_summary(args: argparse.Namespace, result: WorkflowResult) -> dict[str, Any]:
    trace = result.trace if isinstance(result.trace, dict) else {}
    base = base_summary(args)
    knowledge_source = trace.get("knowledge_source")
    if not knowledge_source and result.knowledge_refs:
        first_ref = result.knowledge_refs[0]
        if str(first_ref.get("domain") or "") in SOP_DOMAINS:
            knowledge_source = "sop"
        else:
            knowledge_source = str(first_ref.get("source") or "")

    summary = {
        **base,
        "dry_run": False,
        "action": action_value(result.action),
        "intent": str(result.intent or ""),
        "reason": str(result.reason or ""),
        "risk_flags": [str(flag) for flag in result.risk_flags],
        "workflow_version": str(trace.get("workflow_version") or INTERNAL_WORKFLOW_VERSION),
        "sop_version": trace.get("sop_version") or base.get("sop_version"),
        "knowledge_version": trace.get("knowledge_version"),
        "knowledge_hit_count": int(trace.get("knowledge_hit_count") or len(result.knowledge_refs)),
        "knowledge_source": str(knowledge_source or ""),
        "answer_generator": str(trace.get("answer_generator") or ""),
        "answer_generator_called": bool(trace.get("answer_generator_called", False)),
        "intent_classifier_called": bool(trace.get("intent_classifier_called", False)),
        "intent_source": str(trace.get("intent_source") or ""),
        "answer_generation_source": str(trace.get("answer_generation_source") or ""),
        "answer_generation_status": str(trace.get("answer_generation_status") or ""),
        "answer_error_type": str(trace.get("answer_error_type") or ""),
        "answer_confidence": trace.get("answer_confidence", 0.0),
        "answer_length": int(trace.get("answer_length") or 0),
        "answer_hash": str(trace.get("answer_hash") or ""),
        "answer_preview_truncated": str(trace.get("answer_preview_truncated") or ""),
        "used_history_count": trace.get("used_history_count", trace.get("history_window_size", 0)),
        "used_rag_hit_count": int(trace.get("used_rag_hit_count") or 0),
        "prompt_hash": str(trace.get("prompt_hash") or ""),
        "calls_llm": bool(
            trace.get("calls_llm", False)
            or getattr(args, "use_real_answer_generator", False)
            or getattr(args, "use_real_intent_classifier", False)
        ),
        "product_context_status": str(trace.get("product_context_status") or ""),
        "product_context_source": str(trace.get("product_context_source") or ""),
        "current_product_id_hash": str(trace.get("current_product_id_hash") or ""),
        "current_product_name_hash": str(trace.get("current_product_name_hash") or ""),
        "selected_domain": str(trace.get("selected_domain") or ""),
        "selected_knowledge_base": str(trace.get("selected_knowledge_base") or ""),
        "product_cache_hit": trace.get("product_cache_hit"),
        "product_cache_ttl_seconds": trace.get("product_cache_ttl_seconds"),
        "history_message_count": trace.get("history_message_count", 0),
        "history_window_size": trace.get("history_window_size", 0),
        "pending_human": trace.get("pending_human", False),
        "conversation_id_hash": trace.get("conversation_id_hash", ""),
        "buyer_id_hash": trace.get("buyer_id_hash", base.get("buyer_id_hash", "")),
        "session_id_hash": trace.get("session_id_hash", base.get("session_id_hash", "")),
        "user_id_hash": trace.get("user_id_hash", ""),
        "history_source": trace.get("history_source", ""),
        "rag_enabled": bool(trace.get("rag_enabled", False) or getattr(args, "rag_enabled", False) or getattr(args, "use_fake_rag", False) or getattr(args, "use_real_rag", False)),
        "rag_status": str(trace.get("rag_status") or ("disabled_or_empty" if getattr(args, "rag_enabled", False) else "disabled")),
        "rag_hit_count": int(trace.get("rag_hit_count") or 0),
        "rag_domains": list(trace.get("rag_domains") or []),
        "rag_top_score": trace.get("rag_top_score", 0.0),
        "rag_version_pinned": bool(trace.get("rag_version_pinned", False) or getattr(args, "rag_version", "")),
        "rag_expected_version": str(getattr(args, "expect_rag_version", "") or ""),
        "rag_hit_versions": list(trace.get("rag_hit_versions") or []),
        "rag_version_status": "not_required",
        "rag_shop_status": "not_required",
        "rag_source_type_status": "not_required",
        "rag_hit_content_hashes": list(trace.get("rag_hit_content_hashes") or []),
        "rag_hit_source_types": list(trace.get("rag_hit_source_types") or []),
        "rag_hit_source_ids_hash": list(trace.get("rag_hit_source_ids_hash") or []),
        "rag_hit_shop_ids_hash": list(trace.get("rag_hit_shop_ids_hash") or []),
        "vector_store": str(trace.get("vector_store") or ""),
        "embedding_model": str(trace.get("embedding_model") or ""),
        "retrieval_source": str(trace.get("retrieval_source") or ""),
        "calls_ollama": bool(getattr(args, "use_real_rag", False)),
        "connects_pgvector": bool(getattr(args, "use_real_rag", False)),
    }
    guardrail_status = _guardrail_status(result)
    summary["guardrail_status"] = guardrail_status or "safe"
    if bool(getattr(args, "show_reply", False)):
        summary["final_reply"] = str(result.reply_text or "")
    return _attach_rag_e2e_profile(args, summary)


def base_summary(args: argparse.Namespace) -> dict[str, Any]:
    content = str(args.message or "")
    buyer_id = str(getattr(args, "conversation_buyer_id", "") or args.buyer_id or "")
    session_id = str(getattr(args, "conversation_session_id", "") or args.session_id or "")
    return {
        "backend": "internal",
        "shop_id_hash": _hash_or_empty(args.shop_id),
        "buyer_id_hash": _hash_or_empty(buyer_id),
        "session_id_hash": _hash_or_empty(session_id),
        "message_type": str(args.message_type or "text"),
        "content_length": len(content),
        "content_hash": _short_hash(content),
        "workflow_version": INTERNAL_WORKFLOW_VERSION,
        "knowledge_version": None,
        "history_message_count": 0,
        "history_window_size": 0,
        "pending_human": False,
        "conversation_id_hash": "",
        "history_source": "",
        **_sop_summary(args.sop_file),
    }


def write_summary(summary: dict[str, Any], *, json_only: bool) -> None:
    rendered = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    if json_only:
        print(rendered)
        return
    print("internal_backend_dry_run: no-send summary")
    print(rendered)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run:
        summary = dry_run_summary(args)
        write_summary(summary, json_only=args.json_only)
        return _exit_code(summary)

    try:
        result = asyncio.run(run_engine(args))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    summary = result_summary(args, result)
    write_summary(summary, json_only=args.json_only)
    return _exit_code(summary)


def _guardrail_status(result: WorkflowResult) -> str:
    if result.reason == "output_guardrail_policy_violation":
        return "blocked"
    if "policy_violation" in set(result.risk_flags or []):
        return "blocked"
    return ""


def _attach_rag_e2e_profile(args: argparse.Namespace, summary: dict[str, Any]) -> dict[str, Any]:
    enabled = bool(getattr(args, "rag_e2e_profile", False))
    required = bool(getattr(args, "require_rag_hit", False))
    expected_domain = str(getattr(args, "expect_rag_domain", "") or "")
    expected_version = str(getattr(args, "expect_rag_version", "") or "")
    require_version = bool(getattr(args, "require_rag_version", False))
    expected_shop_hash = _hash_or_empty(getattr(args, "expect_shop_id", ""))
    expected_source_type = str(getattr(args, "expect_rag_source_type", "") or "")
    expected_content_hash = str(getattr(args, "expect_rag_content_hash", "") or "")
    expected_generator = str(getattr(args, "expect_answer_generator", "") or "")
    expected_guardrail = str(getattr(args, "expect_guardrail_status", "") or "")
    require_answer = bool(getattr(args, "require_answer_generated", False))

    rag_domains = [str(domain) for domain in summary.get("rag_domains") or []]
    rag_versions = [str(version) for version in summary.get("rag_hit_versions") or []]
    rag_shop_hashes = [str(value) for value in summary.get("rag_hit_shop_ids_hash") or []]
    rag_source_types = [str(value) for value in summary.get("rag_hit_source_types") or []]
    rag_content_hashes = [str(value) for value in summary.get("rag_hit_content_hashes") or []]
    rag_hit_count = int(summary.get("rag_hit_count") or 0)
    actual_generator = str(summary.get("answer_generator") or "")
    actual_guardrail = str(summary.get("guardrail_status") or "safe")
    answer_length = int(summary.get("answer_length") or 0)

    rag_status = "not_required"
    version_status = "not_required"
    shop_status = "not_required"
    source_type_status = "not_required"
    content_hash_status = "not_required"
    answer_status = "not_required"
    guardrail_status = "not_required"
    failures = []

    if required:
        if rag_hit_count <= 0:
            rag_status = "failed_no_hit"
            failures.append(rag_status)
        elif expected_domain and expected_domain not in rag_domains:
            rag_status = "failed_domain_mismatch"
            failures.append(rag_status)
        else:
            rag_status = "passed"
    elif expected_domain:
        if expected_domain in rag_domains:
            rag_status = "passed"
        elif rag_hit_count > 0:
            rag_status = "failed_domain_mismatch"
            failures.append(rag_status)
        else:
            rag_status = "not_required"

    if require_version or expected_version:
        if rag_hit_count <= 0 and not require_version:
            version_status = "not_required"
        elif not rag_versions:
            version_status = "failed_missing_version"
            failures.append(version_status)
        elif expected_version and any(version != expected_version for version in rag_versions):
            version_status = "failed_version_mismatch"
            failures.append(version_status)
        else:
            version_status = "passed"

    if expected_shop_hash:
        if rag_hit_count <= 0:
            shop_status = "skipped_no_hit"
        elif expected_shop_hash in rag_shop_hashes and all(value == expected_shop_hash for value in rag_shop_hashes):
            shop_status = "passed"
        else:
            shop_status = "failed_shop_mismatch"
            failures.append(shop_status)

    if expected_source_type:
        if rag_hit_count <= 0:
            source_type_status = "skipped_no_hit"
        elif expected_source_type in rag_source_types and all(value == expected_source_type for value in rag_source_types):
            source_type_status = "passed"
        else:
            source_type_status = "failed_source_type_mismatch"
            failures.append(source_type_status)

    if expected_content_hash:
        if rag_hit_count <= 0:
            content_hash_status = "skipped_no_hit"
        elif expected_content_hash in rag_content_hashes:
            content_hash_status = "passed"
        else:
            content_hash_status = "failed_content_hash_mismatch"
            failures.append(content_hash_status)

    if expected_generator:
        if actual_generator == expected_generator and (answer_length > 0 or not require_answer):
            answer_status = "ok"
        else:
            answer_status = "failed"
            failures.append("failed_answer_generator")
    elif require_answer:
        if answer_length > 0:
            answer_status = "ok"
        else:
            answer_status = "failed_required_answer"
            failures.append("failed_required_answer")
    elif actual_generator:
        answer_status = "ok"

    if expected_guardrail:
        if actual_guardrail == expected_guardrail:
            guardrail_status = "passed"
        else:
            guardrail_status = "failed"
            failures.append("failed_guardrail_status")

    summary.update(
        {
            "rag_e2e_profile": enabled,
            "rag_required": required,
            "rag_requirement_status": rag_status,
            "rag_version_pinned": bool(summary.get("rag_version_pinned", False) or getattr(args, "rag_version", "")),
            "rag_expected_version": expected_version,
            "rag_version_status": version_status,
            "rag_shop_status": shop_status,
            "rag_source_type_status": source_type_status,
            "rag_content_hash_status": content_hash_status,
            "answer_generator_required": expected_generator,
            "answer_generation_status": answer_status,
            "guardrail_required": bool(expected_guardrail),
            "guardrail_requirement_status": guardrail_status,
            "rag_e2e_status": "failed" if failures else "ok",
        }
    )
    if failures:
        summary["rag_e2e_failures"] = failures
    return summary


def _exit_code(summary: dict[str, Any]) -> int:
    if summary.get("rag_e2e_profile") and summary.get("rag_e2e_status") == "failed":
        return 1
    return 0


def _hash_or_empty(value: object) -> str:
    text = str(value or "")
    return _short_hash(text) if text else ""


def _sop_summary(sop_file: str | Path | None) -> dict[str, Any]:
    summary = load_sop_fixture_summary(sop_file)
    return {
        **summary,
        "sop_version": str(summary.get("sop_version") or "").strip() or None,
        "sop_domains": list(summary.get("sop_domains") or []),
        "sop_record_count": int(summary.get("sop_record_count") or 0),
    }


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


if __name__ == "__main__":
    raise SystemExit(main())
