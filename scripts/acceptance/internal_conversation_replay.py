"""No-send replay runner for historical conversation messages.

The runner is intentionally read-only and metadata-only. It never writes the
conversation DB, never sends PDD messages, and only emits hashes/counts for
buyer messages, history, answers, and RAG context.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import Session.session_manager  # noqa: F401
from Message.workflow.answer_generator import FakeAnswerGenerator, OpenAICompatibleAnswerGenerator
from Message.workflow.conversation_context import (
    ConversationRecord,
    InMemoryConversationContextRepository,
    SQLiteConversationContextRepository,
    stable_hash,
)
from Message.workflow.embedding_client import OllamaBgeM3EmbeddingClient
from Message.workflow.internal_engine import InternalWorkflowEngine
from Message.workflow.knowledge_repository import ProductKnowledgeRepository
from Message.workflow.sop_provider import SOPProvider
from Message.workflow.types import WorkflowAction, WorkflowContext, WorkflowResult, action_value
from Message.workflow.vector_store import PgVectorStore
from Message.workflow.rag_retriever import VectorStoreRAGRetriever


DEFAULT_SOP_FILE = REPO_ROOT / "docs" / "acceptance" / "fixtures" / "internal_sop_example.md"
DEFAULT_SHOP_ID = "synthetic-shop-1"
DEFAULT_BUYER_ID = "synthetic-buyer-1"
DEFAULT_SESSION_ID = "synthetic-session-1"
DEFAULT_MESSAGE = "\u4e3a\u4ec0\u4e48\u8fd8\u6ca1\u5230"
NO_SEND_FLAGS = {"no_send": True, "calls_fastgpt": False, "sends_pdd": False}
INBOUND_ROLES = {"buyer", "user", "inbound", "customer", "customer_service_inbound"}
ANSWERABLE_DOMAINS = {
    "product_basic",
    "logistics_policy",
    "after_sales_evidence",
    "promotion_policy",
    "sensitive_user_safety",
    "redline_escalation",
}
SHORT_ACKS = {"嗯", "好", "好的", "谢谢", "在吗", "ok", "OK", "Ok", "收到"}
MEDIA_ONLY_MARKERS = {"[图片]", "图片", "[表情]", "表情", "[image]", "image", "[视频]", "视频"}
DOMAIN_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("redline_escalation", ("假货", "投诉", "12315", "赔偿", "曝光")),
    ("sensitive_user_safety", ("孕妇", "小孩", "儿童", "过敏", "敏感肌", "治痘", "医生")),
    ("after_sales_evidence", ("破损", "少发", "错发", "发错", "漏液", "坏了", "拍照")),
    ("logistics_policy", ("为什么还没到", "快递到哪了", "怎么还没发货", "什么时候发货", "物流怎么不动", "什么时候到")),
    ("promotion_policy", ("便宜点", "优惠", "优惠券", "赠品", "包邮", "返差价")),
    ("product_basic", ("怎么用", "成分", "保质期", "规格", "多少钱", "什么规格", "适合什么肤质")),
)
RECALL_PROFILE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "after_sales_evidence": (
        "\u574f\u4e86",
        "\u7834\u4e86",
        "\u788e\u4e86",
        "\u6f0f\u4e86",
        "\u6f0f\u6db2",
        "\u5c11\u4e86",
        "\u5c11\u53d1",
        "\u6ca1\u6536\u5230",
        "\u53d1\u9519",
        "\u9519\u53d1",
        "\u62cd\u7167",
        "\u9000\u6362",
        "\u552e\u540e",
    ),
    "promotion_policy": (
        "\u4fbf\u5b9c",
        "\u4f18\u60e0",
        "\u4f18\u60e0\u5238",
        "\u6d3b\u52a8",
        "\u8d60\u54c1",
        "\u793c\u54c1",
        "\u8fd4\u5dee\u4ef7",
        "\u5dee\u4ef7",
        "\u7acb\u51cf",
        "\u6ee1\u51cf",
        "\u79c1\u4e0b",
    ),
    "redline_escalation": (
        "\u5047\u8d27",
        "\u6295\u8bc9",
        "12315",
        "\u8d54\u507f",
        "\u66dd\u5149",
        "\u5e73\u53f0\u4ecb\u5165",
        "\u7ef4\u6743",
        "\u4e3e\u62a5",
        "\u5de5\u5546",
    ),
    "sensitive_user_safety": (
        "\u5b55\u5987",
        "\u5b9d\u5b9d",
        "\u5c0f\u5b69",
        "\u513f\u7ae5",
        "\u8fc7\u654f",
        "\u654f\u611f\u808c",
        "\u75d8",
        "\u6cbb\u75d8",
        "\u533b\u751f",
        "\u6fc0\u7d20",
        "\u5b89\u5168\u5417",
    ),
    "logistics_policy": (
        "\u5feb\u9012",
        "\u7269\u6d41",
        "\u53d1\u8d27",
        "\u5230\u54ea\u4e86",
        "\u6ca1\u66f4\u65b0",
        "\u4ec0\u4e48\u65f6\u5019\u5230",
        "\u6d3e\u9001",
        "\u63fd\u6536",
    ),
    "product_basic": (
        "\u89c4\u683c",
        "\u6210\u5206",
        "\u600e\u4e48\u7528",
        "\u7528\u6cd5",
        "\u4fdd\u8d28\u671f",
        "\u591a\u5c11\u94b1",
        "\u4ef7\u683c",
        "\u9002\u5408",
        "\u6548\u679c",
    ),
}


@dataclass(frozen=True)
class ReplayMessage:
    replay_id: str
    conversation_id: str
    shop_id: str
    buyer_id: str
    session_id: str
    role: str
    content: str
    created_at: str = ""
    pending_human: bool = False
    answerable_domain: str = ""
    source_table: str = ""
    message_pk: str = ""
    conversation_pk: str = ""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay historical conversations through InternalWorkflowEngine without sending.")
    parser.add_argument("--conversation-db-path", type=Path)
    parser.add_argument("--shop-id", action="append", default=[])
    parser.add_argument("--shop-ids", default="")
    parser.add_argument("--buyer-id", default="")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--since", default="")
    parser.add_argument("--until", default="")
    parser.add_argument("--real-rag", action="store_true")
    parser.add_argument("--rag-shop-id", default="")
    parser.add_argument("--real-llm", action="store_true")
    parser.add_argument("--pg-dsn", default="")
    parser.add_argument("--ollama-base-url", default="")
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--llm-base-url", default="")
    parser.add_argument("--llm-model", default="")
    parser.add_argument("--llm-api-key-env", default="AI_WORKFLOW_LLM_API_KEY")
    parser.add_argument("--llm-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--product-version", default="real-product-v1")
    parser.add_argument("--sop-version", default="sop-test-v1")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--max-messages", type=int, default=0)
    parser.add_argument("--include-pending-human", action="store_true", default=False)
    parser.add_argument("--exclude-pending-human", action="store_true")
    parser.add_argument("--answerable-only", action="store_true")
    parser.add_argument("--answerable-domain", choices=sorted(ANSWERABLE_DOMAINS), default="")
    parser.add_argument("--answerable-max-per-domain", type=int, default=3)
    parser.add_argument("--answerable-min-message-length", type=int, default=2)
    parser.add_argument("--answerable-keyword-profile", default="default")
    parser.add_argument("--exclude-short-acks", action="store_true")
    parser.add_argument("--exclude-system-like", action="store_true")
    parser.add_argument("--exclude-media-only", action="store_true")
    parser.add_argument("--include-redline", action="store_true")
    parser.add_argument("--include-sensitive", action="store_true")
    parser.add_argument("--require-answerable-rag-hit", action="store_true")
    parser.add_argument("--require-answer-generated", action="store_true")
    parser.add_argument("--allow-transfer-for-redline", action="store_true", default=True)
    parser.add_argument("--allow-request-evidence-for-after-sales", action="store_true", default=True)
    parser.add_argument("--answerable-min-pass-rate", type=float, default=0.8)
    parser.add_argument("--answerable-max-unclear-rate", type=float, default=0.3)
    parser.add_argument("--answerable-require-no-failures", action="store_true", default=True)
    parser.add_argument("--selector-audit", action="store_true")
    parser.add_argument("--selector-audit-only", action="store_true")
    parser.add_argument("--selector-audit-include-pending-human", action="store_true")
    parser.add_argument("--selector-audit-max-scan", type=int, default=0)
    parser.add_argument("--selector-audit-domain", choices=sorted(ANSWERABLE_DOMAINS), default="")
    parser.add_argument("--selector-audit-shop-id", action="append", default=[])
    parser.add_argument("--selector-audit-output-samples", action="store_true")
    parser.add_argument("--max-shops", type=int, default=0)
    parser.add_argument("--per-shop-limit", type=int, default=0)
    parser.add_argument("--per-domain-limit", type=int, default=0)
    parser.add_argument("--require-min-domains", type=int, default=0)
    parser.add_argument("--require-min-shops", type=int, default=0)
    parser.add_argument("--allow-empty-shop", action="store_true")
    parser.add_argument("--shop-product-version-map", default="")
    parser.add_argument("--shop-sop-version-map", default="")
    parser.add_argument("--baseline-domains", default="")
    parser.add_argument("--min-cases-per-domain", type=int, default=0)
    parser.add_argument("--max-cases-per-domain", type=int, default=0)
    parser.add_argument("--require-domain-coverage", action="store_true")
    parser.add_argument("--generate-candidate-pool", action="store_true")
    parser.add_argument("--candidate-output", type=Path)
    parser.add_argument("--candidate-max-scan", type=int, default=0)
    parser.add_argument("--candidate-per-shop-limit", type=int, default=0)
    parser.add_argument("--candidate-per-domain-limit", type=int, default=0)
    parser.add_argument("--candidate-include-pending-human", action="store_true")
    parser.add_argument("--candidate-include-unclassified", action="store_true")
    parser.add_argument("--candidate-min-message-length", type=int, default=0)
    parser.add_argument("--candidate-recall-profile", choices=("conservative", "balanced", "broad"), default="conservative")
    parser.add_argument("--candidate-shop-id", action="append", default=[])
    parser.add_argument("--candidate-domain", action="append", default=[])
    parser.add_argument("--benchmark-file", type=Path)
    parser.add_argument("--benchmark-version", default="")
    parser.add_argument("--benchmark-case-id", action="append", default=[])
    parser.add_argument("--benchmark-domain", action="append", default=[])
    parser.add_argument("--benchmark-max-cases", type=int, default=0)
    parser.add_argument("--benchmark-require-rag", action="store_true")
    parser.add_argument("--benchmark-require-answer", action="store_true")
    parser.add_argument("--oracle-routing", action="store_true")
    parser.add_argument("--oracle-domain-from-benchmark", action="store_true", default=True)
    parser.add_argument("--oracle-action-family-from-benchmark", action="store_true")
    parser.add_argument("--diagnose-routing", action="store_true")
    parser.add_argument("--routing-diagnosis-output", type=Path)
    parser.add_argument("--routing-diagnosis-csv", type=Path)
    parser.add_argument("--pending-human-audit", action="store_true")
    parser.add_argument("--pending-human-audit-only", action="store_true")
    parser.add_argument("--pending-human-domain", choices=sorted(ANSWERABLE_DOMAINS), default="")
    parser.add_argument("--pending-human-max-scan", type=int, default=0)
    return parser.parse_args(argv)


def run_replay(args: argparse.Namespace) -> dict[str, Any]:
    shop_ids = _shop_ids(args)
    if not shop_ids:
        return _error_payload("missing_shop_id")
    if len(shop_ids) > 1:
        payloads = []
        for shop_id in shop_ids:
            child = argparse.Namespace(**vars(args))
            child.shop_id = shop_id
            child.shop_ids = ""
            child.selector_audit_shop_id = []
            child._suppress_benchmark_missing = True
            payloads.append(run_replay(child))
        return _merge_shop_payloads(payloads, args)

    shop_id = shop_ids[0]
    if not shop_id:
        return _error_payload("missing_shop_id")

    config_error = _validate_real_args(args)
    if config_error:
        return _error_payload(config_error)

    db_path = getattr(args, "conversation_db_path", None)
    if db_path:
        path = Path(db_path)
        if not path.exists():
            return _missing_payload(path)
        messages, load_status = _load_replay_messages(
            path,
            shop_id=shop_id,
            buyer_id=str(getattr(args, "buyer_id", "") or ""),
            session_id=str(getattr(args, "session_id", "") or ""),
            limit=_effective_limit(args),
            since=str(getattr(args, "since", "") or ""),
            until=str(getattr(args, "until", "") or ""),
            include_pending_human=not bool(getattr(args, "exclude_pending_human", False)),
        )
        if load_status != "ok":
            return _missing_table_payload(load_status, path)
        repository = SQLiteConversationContextRepository(path)
        if bool(getattr(args, "real_rag", False)):
            setattr(args, "_rag_shop_id", _resolve_rag_shop_id(path, shop_id, str(getattr(args, "rag_shop_id", "") or "")))
    else:
        messages = _synthetic_messages(shop_id)
        repository = InMemoryConversationContextRepository(_synthetic_records(shop_id))
        setattr(args, "_rag_shop_id", str(getattr(args, "rag_shop_id", "") or "") or shop_id)

    selection_summary = _empty_selection_summary()
    if bool(getattr(args, "pending_human_audit", False)) or bool(getattr(args, "pending_human_audit_only", False)):
        setattr(args, "_pending_human_audit_summary", _pending_human_audit(messages, args))
    if bool(getattr(args, "pending_human_audit_only", False)):
        return _aggregate_results([], args, status="completed", source_record_count=len(messages))

    benchmark_cases = _load_benchmark_cases(args)
    if benchmark_cases:
        return _run_benchmark_replay(messages, benchmark_cases, args, repository)

    if (
        bool(getattr(args, "answerable_only", False))
        or bool(getattr(args, "selector_audit", False))
        or bool(getattr(args, "selector_audit_only", False))
        or bool(getattr(args, "generate_candidate_pool", False))
    ):
        messages, selection_summary = _select_answerable_messages(messages, args)
    setattr(args, "_answerable_selection_summary", selection_summary)

    if bool(getattr(args, "generate_candidate_pool", False)):
        payload = _aggregate_results([], args, status="completed", source_record_count=selection_summary.get("scanned_total", 0))
        candidate_pool = _candidate_pool_payload(messages, selection_summary)
        payload.update(candidate_pool.get("summary", {}))
        payload["candidates"] = candidate_pool["candidates"]
        output = getattr(args, "candidate_output", None)
        if output:
            path = Path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(candidate_pool, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            payload["candidate_pool_written"] = True
            payload["candidate_output_hash"] = stable_hash(str(path))
        else:
            payload["candidate_pool_written"] = False
        return payload

    if bool(getattr(args, "selector_audit_only", False)):
        return _aggregate_results([], args, status="completed", source_record_count=selection_summary.get("scanned_total", 0))

    max_messages = int(getattr(args, "max_messages", 0) or 0)
    if max_messages > 0:
        messages = messages[:max_messages]

    if not messages:
        return _aggregate_results([], args, status="completed", source_record_count=0)

    engine = _build_engine(args, repository=repository)
    results: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        result = asyncio.run(_run_one(engine, args, message, index))
        results.append(result)
    return _aggregate_results(results, args, status="passed")


async def _run_one(
    engine: InternalWorkflowEngine,
    args: argparse.Namespace,
    message: ReplayMessage,
    index: int,
) -> dict[str, Any]:
    if bool(getattr(args, "oracle_routing", False)) and message.answerable_domain:
        return await _run_one_oracle(engine, args, message, index)
    context = WorkflowContext(
        trace_id=f"conversation-replay-{index}-{stable_hash(message.replay_id)[:12]}",
        shop_id=message.shop_id,
        buyer_id=message.buyer_id,
        customer_uid=message.buyer_id,
        session_id=message.session_id,
        chat_id=message.session_id,
        message_type="text",
        content=message.content,
        metadata={
            "product_version": str(getattr(args, "product_version", "") or ""),
            "sop_version": str(getattr(args, "sop_version", "") or ""),
        },
    )
    try:
        workflow_result = await engine.run(context)
        return _result_row(message, workflow_result, args)
    except Exception as exc:  # noqa: BLE001 - replay should summarize failures without leaking raw content.
        return {
            **_message_identity(message),
            "history_message_count": 0,
            "action": "",
            "intent": "",
            "reason": "engine_exception",
            "rag_status": "error",
            "rag_hit_count": 0,
            "rag_domains": [],
            "rag_versions": [],
            "answer_generation_status": "error",
            "answer_length": 0,
            "answer_hash": "",
            "guardrail_status": "",
            "verdict": "failed",
            "errors": [f"engine_exception:{type(exc).__name__}"],
        }


async def _run_one_oracle(
    engine: InternalWorkflowEngine,
    args: argparse.Namespace,
    message: ReplayMessage,
    index: int,
) -> dict[str, Any]:
    context = WorkflowContext(
        trace_id=f"conversation-replay-oracle-{index}-{stable_hash(message.replay_id)[:12]}",
        shop_id=message.shop_id,
        buyer_id=message.buyer_id,
        customer_uid=message.buyer_id,
        session_id=message.session_id,
        chat_id=message.session_id,
        message_type="text",
        content=message.content,
        metadata={
            "product_version": str(getattr(args, "product_version", "") or ""),
            "sop_version": str(getattr(args, "sop_version", "") or ""),
            "oracle_domain": message.answerable_domain,
        },
    )
    try:
        workflow_result = _oracle_workflow_result(engine, context, message.answerable_domain)
        workflow_result.trace = {
            **(workflow_result.trace if isinstance(workflow_result.trace, dict) else {}),
            "routing_mode": "oracle",
            "oracle_domain_used": True,
            "oracle_domain_hash": stable_hash(message.answerable_domain),
        }
        return _result_row(message, workflow_result, args)
    except Exception as exc:  # noqa: BLE001 - replay should summarize failures without leaking raw content.
        return {
            **_message_identity(message),
            "history_message_count": 0,
            "action": "",
            "intent": "",
            "reason": "oracle_engine_exception",
            "rag_status": "error",
            "rag_hit_count": 0,
            "rag_domains": [],
            "rag_versions": [],
            "answer_generation_status": "error",
            "answer_length": 0,
            "answer_hash": "",
            "guardrail_status": "",
            "routing_mode": "oracle",
            "oracle_domain_used": True,
            "verdict": "failed",
            "errors": [f"oracle_engine_exception:{type(exc).__name__}"],
        }


def _oracle_workflow_result(engine: InternalWorkflowEngine, context: WorkflowContext, domain: str) -> WorkflowResult:
    content = str(context.content or "")
    trace = engine._safe_trace(content)  # noqa: SLF001 - diagnostic-only oracle path.
    conversation_context = engine._load_conversation_context(context)  # noqa: SLF001
    trace = engine._merge_conversation_trace(trace, conversation_context)  # noqa: SLF001
    engine._attach_history(context, conversation_context)  # noqa: SLF001
    trace = {**trace, "routing_mode": "oracle", "oracle_domain_used": True}
    if conversation_context and conversation_context.pending_human:
        return engine._finalize(  # noqa: SLF001
            WorkflowResult(
                action=WorkflowAction.TRANSFER_HUMAN,
                intent="pending_human_lock",
                reason="pending_human_conversation",
                risk_flags=["requires_human", "pending_human"],
                trace=trace,
            ),
            context,
        )
    domain = str(domain or "").strip()
    if domain in {"product_basic", "product_catalog"}:
        return engine._finalize(engine._handle_product_basic(context, content, trace), context)  # noqa: SLF001
    if domain == "redline_escalation":
        return engine._finalize(  # noqa: SLF001
            WorkflowResult(
                action=WorkflowAction.TRANSFER_HUMAN,
                intent="human_escalation_redline",
                reason="oracle_redline_requires_human",
                risk_flags=["redline"],
                trace=trace,
            ),
            context,
        )
    if domain == "after_sales_evidence":
        default = WorkflowResult(
            action=WorkflowAction.REQUEST_EVIDENCE,
            reply_text=str(getattr(engine, "_EVIDENCE_REPLY", "") or ""),
            intent="after_sales_evidence_collection",
            reason="oracle_request_buyer_evidence",
            risk_flags=["needs_evidence"],
            trace=trace,
        )
        result = engine._domain_policy_or_default(  # noqa: SLF001
            context,
            content,
            trace,
            intent="after_sales_evidence_collection",
            domain=domain,
            default=default,
        )
        return engine._finalize(result, context)  # noqa: SLF001
    if domain == "logistics_policy":
        default = WorkflowResult(
            action=WorkflowAction.REPLY,
            reply_text=str(getattr(engine, "_LOGISTICS_REPLY", "") or ""),
            intent="logistics_order_status",
            reason="oracle_logistics_policy",
            risk_flags=["order_context_required"],
            trace=trace,
        )
        result = engine._domain_policy_or_default(  # noqa: SLF001
            context,
            content,
            trace,
            intent="logistics_order_status",
            domain=domain,
            default=default,
        )
        return engine._finalize(result, context)  # noqa: SLF001
    if domain == "promotion_policy":
        default = WorkflowResult(
            action=WorkflowAction.REPLY,
            reply_text=str(getattr(engine, "_PROMOTION_REPLY", "") or ""),
            intent="promotion_policy",
            reason="oracle_promotion_policy",
            risk_flags=["no_private_discount"],
            trace=trace,
        )
        result = engine._domain_policy_or_default(  # noqa: SLF001
            context,
            content,
            trace,
            intent="promotion_policy",
            domain=domain,
            default=default,
        )
        return engine._finalize(result, context)  # noqa: SLF001
    if domain == "sensitive_user_safety":
        default = WorkflowResult(
            action=WorkflowAction.REPLY,
            reply_text=str(getattr(engine, "_SENSITIVE_USER_REPLY", "") or ""),
            intent="sensitive_user_safety",
            reason="oracle_sensitive_user_safety",
            risk_flags=["sensitive_user_safety"],
            trace=trace,
        )
        result = engine._domain_policy_or_default(  # noqa: SLF001
            context,
            content,
            trace,
            intent="sensitive_user_safety",
            domain=domain,
            default=default,
        )
        return engine._finalize(result, context)  # noqa: SLF001
    return engine._finalize(  # noqa: SLF001
        WorkflowResult(
            action=WorkflowAction.FALLBACK,
            intent=domain or "oracle_unknown",
            reason="oracle_domain_not_mapped",
            trace=trace,
        ),
        context,
    )


def _run_benchmark_replay(
    messages: list[ReplayMessage],
    cases: list[dict[str, Any]],
    args: argparse.Namespace,
    repository: Any,
) -> dict[str, Any]:
    by_hash = {}
    for message in messages:
        for content_hash in _content_hashes(message.content):
            by_hash[content_hash] = message
    db_path = Path(getattr(args, "conversation_db_path", "")) if getattr(args, "conversation_db_path", None) else None
    selected_messages: list[ReplayMessage] = []
    selected_cases: list[dict[str, Any]] = []
    synthetic_rows: list[dict[str, Any]] = []
    relevant_cases: list[dict[str, Any]] = []
    for case in cases:
        message, locator_error = _message_from_locator(db_path, case)
        if message is None and locator_error == "locator_hash_mismatch":
            synthetic_rows.append(_benchmark_missing_row(case, reason="locator_hash_mismatch"))
            relevant_cases.append(case)
            continue
        if message is None:
            message = by_hash.get(str(case.get("message_hash") or ""))
        if not message:
            if not bool(getattr(args, "_suppress_benchmark_missing", False)):
                synthetic_rows.append(_benchmark_missing_row(case))
                relevant_cases.append(case)
            continue
        relevant_cases.append(case)
        selected_cases.append(case)
        selected_messages.append(
            ReplayMessage(
                replay_id=message.replay_id,
                conversation_id=message.conversation_id,
                shop_id=message.shop_id,
                buyer_id=message.buyer_id,
                session_id=message.session_id,
                role=message.role,
                content=message.content,
                created_at=message.created_at,
                pending_human=message.pending_human,
                answerable_domain=str(case.get("expected_domain") or ""),
                source_table=message.source_table,
                message_pk=message.message_pk,
                conversation_pk=message.conversation_pk,
            )
        )
    results: list[dict[str, Any]] = list(synthetic_rows)
    if selected_messages:
        engine = _build_engine(args, repository=repository)
        for index, message in enumerate(selected_messages):
            row = asyncio.run(_run_one(engine, args, message, index))
            case = selected_cases[index] if index < len(selected_cases) else {}
            _attach_benchmark_case(row, case)
            results.append(row)
    payload = _aggregate_results(results, args, status="passed", source_record_count=len(cases))
    payload.update(_benchmark_summary(relevant_cases, results, args))
    return payload


def _benchmark_missing_row(case: Mapping[str, Any], *, reason: str = "message_not_found") -> dict[str, Any]:
    domain = str(case.get("expected_domain") or "")
    return {
        "replay_id": stable_hash(str(case.get("case_id") or ""))[:16],
        "case_id": str(case.get("case_id") or ""),
        "conversation_id_hash": "",
        "session_id_hash": str(case.get("session_id_hash") or ""),
        "buyer_id_hash": str(case.get("buyer_id_hash") or ""),
        "shop_id_hash": str(case.get("shop_id_hash") or ""),
        "message_hash": str(case.get("message_hash") or ""),
        "message_length": 0,
        "history_message_count": 0,
        "action": "",
        "intent": "",
        "reason": reason,
        "rag_status": "",
        "rag_hit_count": 0,
        "rag_domains": [],
        "rag_versions": [],
        "answer_generation_status": "",
        "answer_length": 0,
        "answer_hash": "",
        "guardrail_status": "",
        "verdict": "unclear",
        "errors": [reason],
        "answerable_domain": domain,
        "expected_domain": domain,
        "expected_action_family": str(case.get("expected_action_family") or ""),
        "answerable_verdict": "unclear",
        "answerable_errors": [reason],
        "answer_generated": False,
        "rag_required": bool(case.get("requires_rag")),
        "answer_required": bool(case.get("requires_answer")),
    }


def _attach_benchmark_case(row: dict[str, Any], case: Mapping[str, Any]) -> None:
    if not case:
        return
    expected_domain = str(case.get("expected_domain") or "")
    row["case_id"] = str(case.get("case_id") or "")
    row["expected_domain"] = expected_domain
    row["answerable_domain"] = row.get("answerable_domain") or expected_domain
    row["expected_action_family"] = str(case.get("expected_action_family") or row.get("expected_action_family") or "")
    row["benchmark_requires_rag"] = bool(case.get("requires_rag"))
    row["benchmark_requires_answer"] = bool(case.get("requires_answer"))


def _load_benchmark_cases(args: argparse.Namespace) -> list[dict[str, Any]]:
    path = getattr(args, "benchmark_file", None)
    if not path:
        return []
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        setattr(args, "_benchmark_version_loaded", "")
        return [_benchmark_error_case("benchmark_file_error")]
    setattr(args, "_benchmark_version_loaded", str(payload.get("benchmark_version") or ""))
    cases = [case for case in payload.get("cases", []) if isinstance(case, dict)]
    wanted_ids = {str(value) for value in _as_list(getattr(args, "benchmark_case_id", [])) if str(value or "").strip()}
    wanted_domains = {str(value) for value in _as_list(getattr(args, "benchmark_domain", [])) if str(value or "").strip()}
    filtered: list[dict[str, Any]] = []
    for case in cases:
        if wanted_ids and str(case.get("case_id") or "") not in wanted_ids:
            continue
        if wanted_domains and str(case.get("expected_domain") or "") not in wanted_domains:
            continue
        copy = dict(case)
        if bool(getattr(args, "benchmark_require_rag", False)):
            copy["requires_rag"] = True
        if bool(getattr(args, "benchmark_require_answer", False)):
            copy["requires_answer"] = True
        filtered.append(copy)
    max_cases = int(getattr(args, "benchmark_max_cases", 0) or 0)
    if max_cases > 0:
        filtered = filtered[:max_cases]
    return filtered


def _benchmark_error_case(reason: str) -> dict[str, Any]:
    return {
        "case_id": reason,
        "candidate_id": reason,
        "message_hash": reason,
        "expected_domain": "",
        "expected_action_family": "",
        "requires_rag": False,
        "requires_answer": False,
    }


def _benchmark_summary(cases: list[dict[str, Any]], results: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    total = len(cases)
    passed = sum(1 for row in results if row.get("verdict") == "passed")
    failed = sum(1 for row in results if row.get("verdict") == "failed")
    unclear = sum(1 for row in results if row.get("verdict") == "unclear")
    missing = sum(1 for row in results if "message_not_found" in (row.get("errors") or []))
    locator_cases = sum(1 for case in cases if isinstance(case.get("replay_locator"), Mapping))
    locator_resolved = sum(1 for row in results if row.get("locator_resolved"))
    locator_hash_mismatch = sum(1 for row in results if "locator_hash_mismatch" in (row.get("errors") or []))
    return {
        "benchmark_version": str(getattr(args, "_benchmark_version_loaded", "") or getattr(args, "benchmark_version", "") or ""),
        "benchmark_case_count": total,
        "benchmark_replayed_count": max(0, len(results) - missing),
        "benchmark_message_not_found_count": missing,
        "message_not_found_count": missing,
        "locator_case_count": locator_cases,
        "locator_resolved_count": locator_resolved,
        "locator_missing_count": max(0, total - locator_cases),
        "locator_hash_mismatch_count": locator_hash_mismatch,
        "benchmark_passed": passed,
        "benchmark_failed": failed,
        "benchmark_unclear": unclear,
        "benchmark_pass_rate": _rate(passed, total),
        "label_derived_case_count": sum(1 for case in cases if case.get("label_id")),
        "benchmark_domain_counts": _counts(case.get("expected_domain") for case in cases),
    }


def _message_from_locator(db_path: Path | None, case: Mapping[str, Any]) -> tuple[ReplayMessage | None, str]:
    locator = case.get("replay_locator")
    if not db_path or not isinstance(locator, Mapping):
        return None, ""
    source_table = str(locator.get("source_table") or "").strip()
    message_pk = str(locator.get("message_pk") or "").strip()
    if not source_table or not message_pk or not _safe_identifier(source_table):
        return None, "locator_missing"
    try:
        conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None, "locator_sqlite_error"
    try:
        conn.row_factory = sqlite3.Row
        existing_table = _first_existing_table(conn, (source_table,))
        if not existing_table:
            return None, "locator_table_missing"
        columns = _table_columns(conn, existing_table)
        pk_field = _first_field(columns, ("id", "message_id"))
        if not pk_field:
            return None, "locator_pk_missing"
        rows = conn.execute(f"SELECT * FROM {existing_table} WHERE {pk_field} = ? LIMIT 1", (message_pk,)).fetchall()
        if not rows:
            return None, "message_not_found"
        row = rows[0]
        content = _row_text(row, ("content", "message", "text", "body"))
        if not content:
            return None, "message_not_found"
        expected_hash = str(case.get("message_hash") or "").strip()
        if expected_hash and expected_hash not in _content_hashes(content):
            return None, "locator_hash_mismatch"
        shop_id = _row_text(row, ("shop_id",)) or str(locator.get("shop_id") or "")
        buyer_id = _row_text(row, ("buyer_id", "customer_uid", "from_uid", "user_id")) or str(locator.get("buyer_id") or "")
        session_id = _row_text(row, ("session_id",)) or str(locator.get("session_id") or "")
        conversation_id = _row_text(row, ("conversation_id",)) or str(locator.get("conversation_pk") or "") or session_id
        conversation_table = _first_existing_table(conn, ("conversations", "conversation"))
        conversation_columns = _table_columns(conn, conversation_table) if conversation_table else set()
        info = _conversation_info(conn, conversation_table, conversation_columns, shop_id=shop_id).get(session_id, {})
        pending = bool(info.get("pending_human", False))
        message = ReplayMessage(
            replay_id=_row_text(row, ("id", "message_id")) or message_pk,
            conversation_id=str(info.get("conversation_id") or conversation_id),
            shop_id=shop_id,
            buyer_id=str(info.get("buyer_id") or buyer_id),
            session_id=session_id,
            role=_row_text(row, ("role", "sender_type", "direction")).lower(),
            content=content,
            created_at=_row_text(row, ("created_at", "created_time", "timestamp", "time")) or str(locator.get("created_at") or ""),
            pending_human=pending,
            source_table=source_table,
            message_pk=message_pk,
            conversation_pk=str(locator.get("conversation_pk") or ""),
        )
        return message, ""
    except sqlite3.Error:
        return None, "locator_sqlite_error"
    finally:
        conn.close()


def _safe_identifier(value: str) -> bool:
    return value.replace("_", "").isalnum() and not value[0].isdigit()


def _content_hashes(content: object) -> set[str]:
    text = str(content or "")
    full = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {full, full[:16], stable_hash(text)}


def _build_engine(args: argparse.Namespace, *, repository: Any) -> InternalWorkflowEngine:
    answer_generator: Any = FakeAnswerGenerator()
    if bool(getattr(args, "real_llm", False)):
        answer_generator = OpenAICompatibleAnswerGenerator(
            base_url=str(getattr(args, "llm_base_url", "") or ""),
            model=str(getattr(args, "llm_model", "") or ""),
            api_key_env=str(getattr(args, "llm_api_key_env", "") or "AI_WORKFLOW_LLM_API_KEY"),
            timeout_seconds=float(getattr(args, "llm_timeout_seconds", 20.0) or 20.0),
        )
    rag_retriever = None
    if bool(getattr(args, "real_rag", False)):
        rag_retriever = _ReplayRAGRetriever(
            embedding_client=OllamaBgeM3EmbeddingClient(
                base_url=str(getattr(args, "ollama_base_url", "") or ""),
                model=str(getattr(args, "embedding_model", "") or ""),
            ),
            vector_store=PgVectorStore(str(getattr(args, "pg_dsn", "") or "")),
            rag_shop_id=str(getattr(args, "_rag_shop_id", "") or ""),
            product_version=str(getattr(args, "product_version", "") or ""),
            sop_version=str(getattr(args, "sop_version", "") or ""),
            top_k=max(1, int(getattr(args, "top_k", 3) or 3)),
        )
    sop_provider = SOPProvider.from_markdown_file(DEFAULT_SOP_FILE) if DEFAULT_SOP_FILE.exists() else None
    return InternalWorkflowEngine(
        knowledge_repository=ProductKnowledgeRepository(records_source=[]),
        sop_provider=sop_provider,
        conversation_context_repository=repository,
        answer_generator=answer_generator,
        rag_retriever=rag_retriever,
    )


class _ReplayRAGRetriever:
    def __init__(
        self,
        *,
        embedding_client: Any,
        vector_store: Any,
        rag_shop_id: str,
        product_version: str,
        sop_version: str,
        top_k: int,
    ):
        self.embedding_client = embedding_client
        self.vector_store = vector_store
        self.rag_shop_id = str(rag_shop_id or "").strip()
        self.product_version = str(product_version or "").strip()
        self.sop_version = str(sop_version or "").strip()
        self.top_k = top_k
        self._last_stats: dict[str, Any] = {}

    def retrieve(self, context: Any, intent: str, domain: str, query: str, top_k: int = 3):
        version = self.product_version if str(domain or "") in {"product_basic", "product_catalog"} else self.sop_version
        delegate = VectorStoreRAGRetriever(
            embedding_client=self.embedding_client,
            vector_store=self.vector_store,
            version=version,
            top_k=self.top_k or top_k,
        )
        proxy_context = SimpleNamespace(shop_id=self.rag_shop_id or str(getattr(context, "shop_id", "") or ""))
        hits = delegate.retrieve(proxy_context, intent, domain, query, top_k=top_k)
        self._last_stats = delegate.get_last_stats()
        return hits

    def get_last_stats(self) -> dict[str, Any]:
        return dict(self._last_stats)


def _load_replay_messages(
    db_path: Path,
    *,
    shop_id: str,
    buyer_id: str,
    session_id: str,
    limit: int,
    since: str,
    until: str,
    include_pending_human: bool,
) -> tuple[list[ReplayMessage], str]:
    try:
        conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return [], "sqlite_error"
    try:
        conn.row_factory = sqlite3.Row
        message_table = _first_existing_table(conn, ("messages", "conversation_messages", "agent_messages"))
        if not message_table:
            return [], "missing_table"
        conversation_table = _first_existing_table(conn, ("conversations", "conversation"))
        message_columns = _table_columns(conn, message_table)
        conversation_columns = _table_columns(conn, conversation_table) if conversation_table else set()
        session_scope = _session_scope(
            conn,
            conversation_table,
            conversation_columns,
            shop_id=shop_id,
            buyer_id=buyer_id,
            session_id=session_id,
        )
        if conversation_table and "session_id" in message_columns and not session_scope:
            return [], "ok"
        query, values = _message_query(
            message_table,
            message_columns,
            shop_id=shop_id,
            buyer_id=buyer_id,
            session_id=session_id,
            session_scope=session_scope,
            since=since,
            until=until,
            limit=limit,
        )
        rows = conn.execute(query, values).fetchall()
        conversation_info = _conversation_info(conn, conversation_table, conversation_columns, shop_id=shop_id)
        messages: list[ReplayMessage] = []
        for row in rows:
            role = _row_text(row, ("role", "sender_type", "direction")).lower()
            if role not in INBOUND_ROLES:
                continue
            conversation_id = _row_text(row, ("conversation_id", "id"))
            row_session_id = _row_text(row, ("session_id",)) or session_id
            info = conversation_info.get(row_session_id, {})
            is_pending = bool(info.get("pending_human", False))
            if is_pending and not include_pending_human:
                continue
            content = _row_text(row, ("content", "message", "text", "body"))
            if not content:
                continue
            messages.append(
                ReplayMessage(
                    replay_id=_row_text(row, ("id", "message_id")) or f"row-{len(messages)}",
                    conversation_id=str(info.get("conversation_id") or conversation_id or row_session_id),
                    shop_id=_row_text(row, ("shop_id",)) or shop_id,
                    buyer_id=_row_text(row, ("buyer_id", "customer_uid", "from_uid", "user_id"))
                    or str(info.get("buyer_id") or buyer_id),
                    session_id=row_session_id,
                    role=role,
                    content=content,
                    created_at=_row_text(row, ("created_at", "created_time", "timestamp", "time")),
                    pending_human=is_pending,
                    answerable_domain="",
                    source_table=message_table,
                    message_pk=_row_text(row, ("id", "message_id")) or f"row-{len(messages)}",
                    conversation_pk=conversation_id,
                )
            )
        return messages, "ok"
    except sqlite3.Error:
        return [], "sqlite_error"
    finally:
        conn.close()


def _resolve_rag_shop_id(db_path: Path, shop_id: str, explicit_rag_shop_id: str = "") -> str:
    explicit = str(explicit_rag_shop_id or "").strip()
    if explicit:
        return explicit
    try:
        conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return str(shop_id or "")
    try:
        if "shops" not in {_row[0] for _row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            return str(shop_id or "")
        columns = _table_columns(conn, "shops")
        if "id" not in columns or "shop_id" not in columns:
            return str(shop_id or "")
        row = conn.execute("SELECT shop_id FROM shops WHERE id = ? OR shop_id = ? LIMIT 1", (shop_id, shop_id)).fetchone()
        if row and row[0]:
            return str(row[0])
    except sqlite3.Error:
        return str(shop_id or "")
    finally:
        conn.close()
    return str(shop_id or "")


def _message_query(
    table: str,
    columns: set[str],
    *,
    shop_id: str,
    buyer_id: str,
    session_id: str,
    session_scope: list[str],
    since: str,
    until: str,
    limit: int,
) -> tuple[str, list[Any]]:
    where: list[str] = []
    values: list[Any] = []
    if "shop_id" in columns:
        where.append("shop_id = ?")
        values.append(shop_id)
    if buyer_id and "buyer_id" in columns:
        where.append("buyer_id = ?")
        values.append(buyer_id)
    elif buyer_id and "user_id" in columns:
        where.append("user_id = ?")
        values.append(buyer_id)
    if session_id and "session_id" in columns:
        where.append("session_id = ?")
        values.append(session_id)
    elif session_scope and "session_id" in columns:
        placeholders = ",".join("?" for _ in session_scope)
        where.append(f"session_id IN ({placeholders})")
        values.extend(session_scope)
    created_field = _first_field(columns, ("created_at", "created_time", "timestamp", "time"))
    if since and created_field:
        where.append(f"{created_field} >= ?")
        values.append(since)
    if until and created_field:
        where.append(f"{created_field} <= ?")
        values.append(until)
    order = f" ORDER BY {created_field} ASC" if created_field else ""
    limit_value = max(1, int(limit or 10))
    sql = f"SELECT * FROM {table}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += order + f" LIMIT {limit_value}"
    return sql, values


def _session_scope(
    conn: sqlite3.Connection,
    table: str,
    columns: set[str],
    *,
    shop_id: str,
    buyer_id: str,
    session_id: str,
) -> list[str]:
    if not table or "session_id" not in columns:
        return [session_id] if session_id else []
    where: list[str] = []
    values: list[Any] = []
    if "shop_id" in columns:
        where.append("shop_id = ?")
        values.append(shop_id)
    if buyer_id and "buyer_id" in columns:
        where.append("buyer_id = ?")
        values.append(buyer_id)
    elif buyer_id and "user_id" in columns:
        where.append("user_id = ?")
        values.append(buyer_id)
    if session_id:
        where.append("session_id = ?")
        values.append(session_id)
    if not where:
        return []
    sql = f"SELECT DISTINCT session_id FROM {table} WHERE " + " AND ".join(where)
    return [str(row[0]) for row in conn.execute(sql, values).fetchall() if row[0]]


def _conversation_info(
    conn: sqlite3.Connection,
    table: str,
    columns: set[str],
    *,
    shop_id: str,
) -> dict[str, dict[str, Any]]:
    if not table:
        return {}
    where = " WHERE shop_id = ?" if "shop_id" in columns else ""
    values: list[Any] = [shop_id] if where else []
    result: dict[str, dict[str, Any]] = {}
    for row in conn.execute(f"SELECT * FROM {table}{where}", values).fetchall():
        session_id = _row_text(row, ("session_id",))
        if session_id:
            result[session_id] = {
                "conversation_id": _row_text(row, ("conversation_id", "id")),
                "buyer_id": _row_text(row, ("buyer_id", "customer_uid", "from_uid", "user_id")),
                "pending_human": _row_pending_human(row),
            }
    return result


def _synthetic_messages(shop_id: str) -> list[ReplayMessage]:
    return [
        ReplayMessage(
            replay_id="synthetic-replay-1",
            conversation_id="synthetic-conversation-1",
            shop_id=shop_id,
            buyer_id=DEFAULT_BUYER_ID,
            session_id=DEFAULT_SESSION_ID,
            role="buyer",
            content=DEFAULT_MESSAGE,
            created_at="2026-05-21T10:00:00",
            answerable_domain="logistics_policy",
            source_table="synthetic",
            message_pk="synthetic-replay-1",
            conversation_pk="synthetic-conversation-1",
        )
    ]


def _synthetic_records(shop_id: str) -> list[ConversationRecord]:
    return [
        ConversationRecord(
            shop_id=shop_id,
            user_id="",
            buyer_id=DEFAULT_BUYER_ID,
            session_id=DEFAULT_SESSION_ID,
            role="buyer",
            message_type="text",
            content="synthetic hashed history",
            created_at="2026-05-21T09:59:00",
            source="synthetic_replay",
        )
    ]


def _result_row(message: ReplayMessage, result: WorkflowResult, args: argparse.Namespace) -> dict[str, Any]:
    trace = result.trace if isinstance(result.trace, dict) else {}
    action = action_value(result.action)
    guardrail_status = _guardrail_status(result)
    errors: list[str] = []
    verdict = "passed"
    if message.pending_human and action != WorkflowAction.TRANSFER_HUMAN.value:
        verdict = "failed"
        errors.append("pending_human_not_transferred")
    if guardrail_status == "blocked" and action == WorkflowAction.REPLY.value:
        verdict = "failed"
        errors.append("blocked_guardrail_reply")
    rag_status = str(trace.get("rag_status") or "")
    if (
        bool(getattr(args, "real_rag", False))
        and rag_status == "empty"
        and int(trace.get("rag_hit_count") or 0) == 0
        and verdict == "passed"
    ):
        verdict = "unclear"
        errors.append("rag_miss")
    if bool(getattr(args, "real_llm", False)):
        answer_status = str(trace.get("answer_generation_status") or "")
        if answer_status.startswith("failed") or answer_status in {"error", "empty"}:
            verdict = "unclear" if verdict == "passed" else verdict
            errors.append("llm_error")
        if action == WorkflowAction.REPLY.value and int(trace.get("answer_length") or 0) == 0:
            verdict = "unclear" if verdict == "passed" else verdict
            errors.append("empty_answer")
    row = {
        **_message_identity(message),
        "history_message_count": int(trace.get("history_message_count") or 0),
        "action": action,
        "intent": str(result.intent or ""),
        "reason": str(result.reason or ""),
        "rag_status": str(trace.get("rag_status") or ("disabled" if not getattr(args, "real_rag", False) else "empty")),
        "rag_hit_count": int(trace.get("rag_hit_count") or 0),
        "rag_domains": list(trace.get("rag_domains") or []),
        "rag_versions": list(trace.get("rag_hit_versions") or []),
        "answer_generation_status": str(trace.get("answer_generation_status") or ""),
        "answer_length": int(trace.get("answer_length") or len(result.reply_text or "")),
        "answer_hash": str(trace.get("answer_hash") or (stable_hash(result.reply_text) if result.reply_text else "")),
        "guardrail_status": guardrail_status or "safe",
        "routing_mode": str(trace.get("routing_mode") or "production"),
        "oracle_domain_used": bool(trace.get("oracle_domain_used", False)),
        "verdict": verdict,
        "errors": errors,
    }
    if bool(getattr(args, "answerable_only", False)) or message.answerable_domain:
        _apply_answerable_verdict(row, message, args)
    return row


def _apply_answerable_verdict(row: dict[str, Any], message: ReplayMessage, args: argparse.Namespace) -> None:
    domain = message.answerable_domain or _classify_answerable_domain(message.content)
    action = str(row.get("action") or "")
    answer_length = int(row.get("answer_length") or 0)
    answer_status = str(row.get("answer_generation_status") or "")
    rag_hit_count = int(row.get("rag_hit_count") or 0)
    guardrail_status = str(row.get("guardrail_status") or "")
    answer_required = _answer_required_for_domain(domain, action, args)
    rag_required = bool(getattr(args, "require_answerable_rag_hit", False)) and domain not in {
        "redline_escalation",
        "sensitive_user_safety",
    }
    errors: list[str] = []
    verdict = "passed"
    if domain == "redline_escalation":
        if action != WorkflowAction.TRANSFER_HUMAN.value and guardrail_status != "blocked":
            errors.append("redline_not_transferred")
    elif domain == "after_sales_evidence":
        allowed = {WorkflowAction.REQUEST_EVIDENCE.value, WorkflowAction.REPLY.value, WorkflowAction.TRANSFER_HUMAN.value}
        if action not in allowed:
            errors.append("after_sales_unexpected_action")
    elif domain == "sensitive_user_safety":
        allowed = {WorkflowAction.REPLY.value, WorkflowAction.TRANSFER_HUMAN.value, WorkflowAction.FALLBACK.value}
        if action not in allowed and guardrail_status != "blocked":
            errors.append("sensitive_unexpected_action")
    elif action != WorkflowAction.REPLY.value:
        errors.append("answerable_not_reply")
    if rag_required and rag_hit_count <= 0:
        errors.append("answerable_rag_miss")
    if answer_required and not (answer_status == "ok" and answer_length > 0):
        errors.append("answer_not_generated")
    if action == WorkflowAction.FALLBACK.value and domain not in {"sensitive_user_safety"}:
        errors.append("answerable_fallback")
    if errors:
        verdict = "failed" if bool(getattr(args, "answerable_require_no_failures", True)) else "unclear"
    row["answerable_domain"] = domain
    row["expected_action_family"] = _expected_action_family(domain)
    row["answerable_verdict"] = verdict
    row["answerable_errors"] = errors
    row["answer_generated"] = answer_length > 0 and answer_status in {"", "ok"}
    row["rag_required"] = rag_required
    row["answer_required"] = answer_required
    if verdict == "failed":
        row["verdict"] = "failed"
        existing = list(row.get("errors") or [])
        for error in errors:
            if error not in existing:
                existing.append(error)
        row["errors"] = existing
    elif verdict == "unclear" and row.get("verdict") == "passed":
        row["verdict"] = "unclear"


def _answer_required_for_domain(domain: str, action: str, args: argparse.Namespace) -> bool:
    if not bool(getattr(args, "require_answer_generated", False)):
        return False
    if domain == "redline_escalation":
        return False
    if action in {WorkflowAction.TRANSFER_HUMAN.value, WorkflowAction.REQUEST_EVIDENCE.value}:
        return False
    return True


def _expected_action_family(domain: str) -> str:
    if domain == "redline_escalation":
        return "transfer_human_or_blocked"
    if domain == "after_sales_evidence":
        return "request_evidence_or_reply"
    if domain == "sensitive_user_safety":
        return "safe_reply_or_transfer"
    return "reply"


def _message_identity(message: ReplayMessage) -> dict[str, Any]:
    return {
        "replay_id": stable_hash(message.replay_id)[:16],
        "conversation_id_hash": stable_hash(message.conversation_id),
        "session_id_hash": stable_hash(message.session_id),
        "buyer_id_hash": stable_hash(message.buyer_id),
        "shop_id_hash": stable_hash(message.shop_id),
        "message_hash": stable_hash(message.content),
        "message_length": len(message.content),
        "locator_hash": stable_hash("|".join([message.source_table, message.message_pk, message.session_id])),
        "locator_resolved": bool(message.source_table and message.message_pk),
    }


def _aggregate_results(
    results: list[dict[str, Any]],
    args: argparse.Namespace,
    *,
    status: str,
    source_record_count: int | None = None,
) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for row in results if row.get("verdict") == "passed")
    failed = sum(1 for row in results if row.get("verdict") == "failed")
    unclear = sum(1 for row in results if row.get("verdict") == "unclear")
    replayed = total
    action_counts = _counts(row.get("action") for row in results)
    intent_counts = _counts(row.get("intent") for row in results)
    rag_hit_count = sum(1 for row in results if int(row.get("rag_hit_count") or 0) > 0)
    answer_generated = sum(1 for row in results if int(row.get("answer_length") or 0) > 0)
    guardrail_blocked = sum(1 for row in results if row.get("guardrail_status") == "blocked")
    transfer_human = sum(1 for row in results if row.get("action") == WorkflowAction.TRANSFER_HUMAN.value)
    pending_human_count = sum(1 for message in results if "pending_human_not_transferred" in (message.get("errors") or []))
    pending_human_count += sum(1 for row in results if row.get("intent") == "pending_human_lock")
    rag_miss_count = sum(1 for row in results if "rag_miss" in (row.get("errors") or []))
    llm_error_count = sum(1 for row in results if "llm_error" in (row.get("errors") or []))
    empty_answer_count = sum(1 for row in results if "empty_answer" in (row.get("errors") or []))
    answerable_rows = [row for row in results if row.get("answerable_domain")]
    answerable_total = len(answerable_rows)
    answerable_passed = sum(1 for row in answerable_rows if row.get("answerable_verdict") == "passed")
    answerable_failed = sum(1 for row in answerable_rows if row.get("answerable_verdict") == "failed")
    answerable_unclear = sum(1 for row in answerable_rows if row.get("answerable_verdict") == "unclear")
    answerable_rag_hits = sum(1 for row in answerable_rows if int(row.get("rag_hit_count") or 0) > 0)
    answerable_answer_generated = sum(1 for row in answerable_rows if bool(row.get("answer_generated")))
    selection_summary = getattr(args, "_answerable_selection_summary", _empty_selection_summary())
    pending_audit_summary = getattr(args, "_pending_human_audit_summary", {})
    domains_required = _baseline_domains(args)
    domains_present = sorted({str(domain) for domain in (selection_summary.get("selected_by_domain") or {}).keys() if domain})
    domains_missing = [domain for domain in domains_required if domain not in domains_present]
    replay_pass_rate_by_domain = _domain_rate(answerable_rows, "passed")
    replay_unclear_by_domain = _domain_count(answerable_rows, "unclear")
    replay_failed_by_domain = _domain_count(answerable_rows, "failed")
    domain_coverage_status = "skipped"
    if domains_required:
        domain_coverage_status = "passed" if not domains_missing else "failed"
    final_status = "failed" if failed else status
    if bool(getattr(args, "answerable_only", False)):
        answerable_pass_rate = _rate(answerable_passed, answerable_total)
        answerable_unclear_rate = _rate(answerable_unclear, answerable_total)
        if answerable_failed and bool(getattr(args, "answerable_require_no_failures", True)):
            final_status = "failed"
        elif answerable_total and answerable_pass_rate < float(getattr(args, "answerable_min_pass_rate", 0.8) or 0.8):
            final_status = "failed"
        elif answerable_total and answerable_unclear_rate > float(getattr(args, "answerable_max_unclear_rate", 0.3) or 0.3):
            final_status = "failed"
    if bool(getattr(args, "require_domain_coverage", False)) and domains_missing:
        final_status = "failed"
    if int(getattr(args, "require_min_domains", 0) or 0) > 0 and len(domains_present) < int(getattr(args, "require_min_domains", 0) or 0):
        final_status = "failed"
    return {
        "status": final_status,
        "total": total,
        "source_record_count": total if source_record_count is None else int(source_record_count),
        "replayed": replayed,
        "skipped": 0,
        "passed": passed,
        "failed": failed,
        "unclear": unclear,
        "pass_rate": _rate(passed, total),
        "fail_rate": _rate(failed, total),
        "unclear_rate": _rate(unclear, total),
        **NO_SEND_FLAGS,
        "calls_llm": bool(getattr(args, "real_llm", False)),
        "calls_ollama": bool(getattr(args, "real_rag", False)),
        "connects_pgvector": bool(getattr(args, "real_rag", False)),
        "action_counts": action_counts,
        "intent_counts": intent_counts,
        "guardrail_blocked_count": guardrail_blocked,
        "transfer_human_count": transfer_human,
        "rag_hit_rate": _rate(rag_hit_count, total),
        "answer_generated_rate": _rate(answer_generated, total),
        "pending_human_count": pending_human_count,
        "history_loaded_count": sum(1 for row in results if int(row.get("history_message_count") or 0) > 0),
        "cross_shop_failures": 0,
        "error_type": "",
        "rag_miss_count": rag_miss_count,
        "llm_error_count": llm_error_count,
        "empty_answer_count": empty_answer_count,
        "locator_case_count": sum(1 for row in results if row.get("locator_hash")),
        "locator_resolved_count": sum(1 for row in results if row.get("locator_resolved")),
        "locator_missing_count": sum(1 for row in results if "message_not_found" in (row.get("errors") or [])),
        "locator_hash_mismatch_count": sum(1 for row in results if "locator_hash_mismatch" in (row.get("errors") or [])),
        **selection_summary,
        "pending_human_count": pending_human_count or int(selection_summary.get("pending_human_count") or 0),
        "answerable_total": answerable_total,
        "answerable_passed": answerable_passed,
        "answerable_failed": answerable_failed,
        "answerable_unclear": answerable_unclear,
        "answerable_pass_rate": _rate(answerable_passed, answerable_total),
        "answerable_rag_hit_rate": _rate(answerable_rag_hits, answerable_total),
        "answerable_answer_generated_rate": _rate(answerable_answer_generated, answerable_total),
        "answerable_by_domain": _counts(row.get("answerable_domain") for row in answerable_rows),
        "answerable_failures_by_domain": _counts(
            row.get("answerable_domain") for row in answerable_rows if row.get("answerable_verdict") == "failed"
        ),
        "answerable_unclear_by_domain": _counts(
            row.get("answerable_domain") for row in answerable_rows if row.get("answerable_verdict") == "unclear"
        ),
        "domain_coverage_status": domain_coverage_status,
        "domains_required": domains_required,
        "domains_present": domains_present,
        "domains_missing": domains_missing,
        "replay_pass_rate_by_domain": replay_pass_rate_by_domain,
        "replay_unclear_by_domain": replay_unclear_by_domain,
        "replay_failed_by_domain": replay_failed_by_domain,
        "unclear_reason_counts": _reason_counts(results, verdict="unclear"),
        "rag_miss_reason_counts": _rag_miss_reason_counts(results),
        "failure_reason_counts": _reason_counts(results, verdict="failed"),
        "pending_human_scanned": int(pending_audit_summary.get("pending_human_scanned") or 0),
        "pending_human_answerable_candidates": int(pending_audit_summary.get("pending_human_answerable_candidates") or 0),
        "pending_human_by_domain": dict(pending_audit_summary.get("pending_human_by_domain") or {}),
        "pending_human_exclusion_reasons": dict(pending_audit_summary.get("pending_human_exclusion_reasons") or {}),
        "benchmark_version": str(getattr(args, "_benchmark_version_loaded", "") or getattr(args, "benchmark_version", "") or ""),
        "benchmark_case_count": 0,
        "benchmark_replayed_count": 0,
        "benchmark_message_not_found_count": 0,
        "benchmark_passed": 0,
        "benchmark_failed": 0,
        "benchmark_unclear": 0,
        "benchmark_pass_rate": 0.0,
        "results": results,
    }


def _select_answerable_messages(
    messages: list[ReplayMessage],
    args: argparse.Namespace,
) -> tuple[list[ReplayMessage], dict[str, Any]]:
    selected: list[ReplayMessage] = []
    selected_by_domain: dict[str, int] = {}
    excluded_by_reason: dict[str, int] = {}
    samples: list[dict[str, Any]] = []
    max_per_domain = _effective_per_domain_limit(args)
    min_length = max(0, int(getattr(args, "candidate_min_message_length", 0) or getattr(args, "answerable_min_message_length", 2) or 2))
    domain_filter = str(getattr(args, "selector_audit_domain", "") or "") or str(getattr(args, "answerable_domain", "") or "")
    candidate_domains = [str(value) for value in _as_list(getattr(args, "candidate_domain", [])) if str(value or "").strip()]
    if candidate_domains and not domain_filter:
        domain_filter = candidate_domains[0] if len(candidate_domains) == 1 else ""
    include_redline = bool(getattr(args, "include_redline", False))
    include_sensitive = bool(getattr(args, "include_sensitive", False))
    include_pending_for_audit = bool(getattr(args, "selector_audit_include_pending_human", False)) or bool(getattr(args, "candidate_include_pending_human", False))
    max_scan = int(getattr(args, "candidate_max_scan", 0) or getattr(args, "selector_audit_max_scan", 0) or 0)
    scanned_messages = messages[:max_scan] if max_scan > 0 else messages
    pending_human_count = sum(1 for message in scanned_messages if message.pending_human)
    media_only_count = 0
    short_ack_count = 0
    system_like_count = 0
    unclassified_count = 0
    candidate_total = 0
    for message in scanned_messages:
        content = message.content.strip()
        predicted_domain = message.answerable_domain or _classify_answerable_domain_for_profile(
            content,
            str(getattr(args, "candidate_recall_profile", "conservative") or "conservative"),
        )
        exclusion_reason = ""
        if message.pending_human and not include_pending_for_audit and (
            bool(getattr(args, "exclude_pending_human", False)) or not bool(getattr(args, "include_pending_human", False))
        ):
            exclusion_reason = "pending_human_excluded"
            _inc(excluded_by_reason, exclusion_reason)
            _sample_audit(samples, message, predicted_domain, exclusion_reason, args)
            continue
        if _is_media_only(content):
            media_only_count += 1
            exclusion_reason = "media_only"
            _inc(excluded_by_reason, exclusion_reason)
            _sample_audit(samples, message, predicted_domain, exclusion_reason, args)
            continue
        if _is_short_ack(content) or len(content) < min_length:
            short_ack_count += 1
            exclusion_reason = "short_ack"
            _inc(excluded_by_reason, exclusion_reason)
            _sample_audit(samples, message, predicted_domain, exclusion_reason, args)
            continue
        if _is_system_like(content):
            system_like_count += 1
            exclusion_reason = "system_like"
            _inc(excluded_by_reason, exclusion_reason)
            _sample_audit(samples, message, predicted_domain, exclusion_reason, args)
            continue
        domain = predicted_domain
        if not domain:
            unclassified_count += 1
            exclusion_reason = "selector_unclassified"
            _inc(excluded_by_reason, exclusion_reason)
            _sample_audit(samples, message, predicted_domain, exclusion_reason, args)
            continue
        candidate_total += 1
        if domain == "redline_escalation" and not include_redline and domain_filter != domain:
            exclusion_reason = "redline_excluded"
            _inc(excluded_by_reason, exclusion_reason)
            _sample_audit(samples, message, predicted_domain, exclusion_reason, args)
            continue
        if domain == "sensitive_user_safety" and not include_sensitive and domain_filter != domain:
            exclusion_reason = "sensitive_excluded"
            _inc(excluded_by_reason, exclusion_reason)
            _sample_audit(samples, message, predicted_domain, exclusion_reason, args)
            continue
        if candidate_domains and domain not in candidate_domains:
            exclusion_reason = "domain_filtered"
            _inc(excluded_by_reason, exclusion_reason)
            _sample_audit(samples, message, predicted_domain, exclusion_reason, args)
            continue
        if domain_filter and domain != domain_filter:
            exclusion_reason = "domain_filtered"
            _inc(excluded_by_reason, exclusion_reason)
            _sample_audit(samples, message, predicted_domain, exclusion_reason, args)
            continue
        if selected_by_domain.get(domain, 0) >= max_per_domain:
            exclusion_reason = "domain_limit"
            _inc(excluded_by_reason, exclusion_reason)
            _sample_audit(samples, message, predicted_domain, exclusion_reason, args)
            continue
        selected_by_domain[domain] = selected_by_domain.get(domain, 0) + 1
        selected.append(
            ReplayMessage(
                replay_id=message.replay_id,
                conversation_id=message.conversation_id,
                shop_id=message.shop_id,
                buyer_id=message.buyer_id,
                session_id=message.session_id,
                role=message.role,
                content=message.content,
                created_at=message.created_at,
                pending_human=message.pending_human,
                answerable_domain=domain,
            )
        )
        _sample_audit(samples, message, predicted_domain, "", args)
    selected_shop_counts = _counts(message.shop_id for message in selected)
    domain_counts_by_shop: dict[str, dict[str, int]] = {}
    for message in selected:
        shop_hash = stable_hash(message.shop_id)[:16]
        domain_counts_by_shop.setdefault(shop_hash, {})
        _inc(domain_counts_by_shop[shop_hash], message.answerable_domain)
    excluded_total = sum(excluded_by_reason.values())
    return selected, {
        "scanned_total": len(scanned_messages),
        "candidate_total": candidate_total,
        "selected_total": len(selected),
        "selected_by_domain": selected_by_domain,
        "excluded_total": excluded_total,
        "excluded_by_reason": excluded_by_reason,
        "pending_human_count": pending_human_count,
        "pending_human_excluded_count": excluded_by_reason.get("pending_human_excluded", 0),
        "media_only_count": media_only_count,
        "short_ack_count": short_ack_count,
        "system_like_count": system_like_count,
        "unclassified_count": unclassified_count,
        "skipped_short_ack": short_ack_count,
        "skipped_media_only": media_only_count,
        "skipped_pending_human": excluded_by_reason.get("pending_human_excluded", 0),
        "skipped_unclassified": unclassified_count + excluded_by_reason.get("domain_filtered", 0) + excluded_by_reason.get("domain_limit", 0),
        "shop_counts": selected_shop_counts,
        "domain_counts_by_shop": domain_counts_by_shop,
        "message_hashes": [stable_hash(message.content) for message in selected],
        "domain_counts": dict(selected_by_domain),
        "samples": samples if bool(getattr(args, "selector_audit_output_samples", False)) else [],
        "selector_profile": str(getattr(args, "candidate_recall_profile", "conservative") or "conservative"),
    }


def _candidate_pool_payload(messages: list[ReplayMessage], selection_summary: Mapping[str, Any]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for message in messages:
        domain = message.answerable_domain or _classify_answerable_domain_for_profile(
            message.content,
            str(selection_summary.get("selector_profile") or "conservative"),
        )
        candidate_id = "cand-" + stable_hash("|".join([message.shop_id, message.session_id, stable_hash(message.content), domain]))[:16]
        candidates.append(
            {
                "candidate_id": candidate_id,
                "message_id_hash": stable_hash(message.replay_id),
                "conversation_id_hash": stable_hash(message.conversation_id),
                "session_id_hash": stable_hash(message.session_id),
                "buyer_id_hash": stable_hash(message.buyer_id),
                "shop_id_hash": stable_hash(message.shop_id),
                "message_hash": stable_hash(message.content),
                "message_length": len(message.content),
                "predicted_domain": domain,
                "selector_score": 1.0 if domain else 0.0,
                "exclusion_reason": "",
                "pending_human": bool(message.pending_human),
                "created_at_bucket": _created_at_bucket(message.created_at),
                "source": "history",
            }
        )
    return {
        "summary": {
            "candidate_pool_status": "completed",
            "candidate_total": int(selection_summary.get("candidate_total") or len(candidates)),
            "selected_total": len(candidates),
            "selected_by_domain": dict(selection_summary.get("selected_by_domain") or _counts(candidate.get("predicted_domain") for candidate in candidates)),
            "selected_by_shop": _counts(candidate.get("shop_id_hash") for candidate in candidates),
            "excluded_by_reason": dict(selection_summary.get("excluded_by_reason") or {}),
            "pending_human_candidate_count": sum(1 for candidate in candidates if candidate.get("pending_human")),
            "unclassified_count": int(selection_summary.get("unclassified_count") or 0),
        },
        "candidates": candidates,
    }


def _created_at_bucket(value: str) -> str:
    text = str(value or "")
    return text[:10] if len(text) >= 10 else ""


def _pending_human_audit(messages: list[ReplayMessage], args: argparse.Namespace) -> dict[str, Any]:
    max_scan = int(getattr(args, "pending_human_max_scan", 0) or 0)
    domain_filter = str(getattr(args, "pending_human_domain", "") or "")
    scanned = [message for message in (messages[:max_scan] if max_scan > 0 else messages) if message.pending_human]
    by_domain: dict[str, int] = {}
    exclusions: dict[str, int] = {}
    candidates = 0
    for message in scanned:
        domain = _classify_answerable_domain(message.content)
        if domain_filter and domain != domain_filter:
            _inc(exclusions, "domain_filtered")
            continue
        if not domain:
            _inc(exclusions, "selector_unclassified")
            continue
        candidates += 1
        _inc(by_domain, domain)
    return {
        "pending_human_scanned": len(scanned),
        "pending_human_answerable_candidates": candidates,
        "pending_human_by_domain": by_domain,
        "pending_human_exclusion_reasons": exclusions,
    }


def _empty_selection_summary() -> dict[str, Any]:
    return {
        "scanned_total": 0,
        "candidate_total": 0,
        "selected_total": 0,
        "selected_by_domain": {},
        "excluded_total": 0,
        "excluded_by_reason": {},
        "pending_human_count": 0,
        "pending_human_excluded_count": 0,
        "media_only_count": 0,
        "short_ack_count": 0,
        "system_like_count": 0,
        "unclassified_count": 0,
        "skipped_short_ack": 0,
        "skipped_media_only": 0,
        "skipped_pending_human": 0,
        "skipped_unclassified": 0,
        "shop_counts": {},
        "domain_counts_by_shop": {},
        "message_hashes": [],
        "domain_counts": {},
        "samples": [],
        "selector_profile": "",
    }


def _classify_answerable_domain(content: str) -> str:
    for domain, keywords in DOMAIN_KEYWORDS:
        if any(keyword in content for keyword in keywords):
            return domain
    return ""


def _classify_answerable_domain_for_profile(content: str, profile: str) -> str:
    base = _classify_answerable_domain(content)
    if base or profile == "conservative":
        return base
    for domain, keywords in RECALL_PROFILE_KEYWORDS.items():
        if any(keyword in content for keyword in keywords):
            return domain
    return ""


def _shop_ids(args: argparse.Namespace) -> list[str]:
    values: list[str] = []
    explicit = False
    for value in _as_list(getattr(args, "selector_audit_shop_id", [])):
        explicit = True
        values.extend(str(value or "").split(","))
    for value in _as_list(getattr(args, "candidate_shop_id", [])):
        explicit = True
        values.extend(str(value or "").split(","))
    for value in _as_list(getattr(args, "shop_id", [])):
        explicit = True
        values.extend(str(value or "").split(","))
    shop_ids_raw = str(getattr(args, "shop_ids", "") or "")
    if shop_ids_raw:
        explicit = True
        values.extend(shop_ids_raw.split(","))
    cleaned = [value.strip() for value in values if value and value.strip()]
    if not cleaned and not explicit:
        cleaned = [DEFAULT_SHOP_ID]
    max_shops = int(getattr(args, "max_shops", 0) or 0)
    if max_shops > 0:
        cleaned = cleaned[:max_shops]
    return cleaned


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _effective_limit(args: argparse.Namespace) -> int:
    candidate_scan = int(getattr(args, "candidate_max_scan", 0) or 0)
    if candidate_scan > 0:
        return candidate_scan
    per_shop = int(getattr(args, "per_shop_limit", 0) or 0)
    if per_shop > 0:
        return per_shop
    candidate_per_shop = int(getattr(args, "candidate_per_shop_limit", 0) or 0)
    if candidate_per_shop > 0:
        return candidate_per_shop
    return int(getattr(args, "limit", 10) or 10)


def _effective_per_domain_limit(args: argparse.Namespace) -> int:
    for name in ("candidate_per_domain_limit", "per_domain_limit", "max_cases_per_domain", "answerable_max_per_domain"):
        value = int(getattr(args, name, 0) or 0)
        if value > 0:
            return value
    return 3


def _baseline_domains(args: argparse.Namespace) -> list[str]:
    raw = str(getattr(args, "baseline_domains", "") or "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def _inc(target: dict[str, int], key: object, amount: int = 1) -> None:
    text = str(key or "")
    if not text:
        return
    target[text] = target.get(text, 0) + amount


def _sample_audit(samples: list[dict[str, Any]], message: ReplayMessage, domain: str, reason: str, args: argparse.Namespace) -> None:
    if not bool(getattr(args, "selector_audit_output_samples", False)):
        return
    if len(samples) >= 50:
        return
    samples.append(
        {
            "message_hash": stable_hash(message.content),
            "message_length": len(message.content),
            "shop_id_hash": stable_hash(message.shop_id),
            "buyer_id_hash": stable_hash(message.buyer_id),
            "session_id_hash": stable_hash(message.session_id),
            "predicted_domain": domain,
            "exclusion_reason": reason,
        }
    )


def _domain_count(rows: list[dict[str, Any]], verdict: str) -> dict[str, int]:
    return _counts(row.get("answerable_domain") for row in rows if row.get("answerable_verdict") == verdict)


def _domain_rate(rows: list[dict[str, Any]], verdict: str) -> dict[str, float]:
    totals = _counts(row.get("answerable_domain") for row in rows)
    counts = _domain_count(rows, verdict)
    return {domain: _rate(counts.get(domain, 0), total) for domain, total in totals.items()}


def _reason_counts(rows: list[dict[str, Any]], *, verdict: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if row.get("verdict") != verdict:
            continue
        for error in row.get("answerable_errors") or row.get("errors") or []:
            _inc(counts, _normalize_reason(error))
    return counts


def _rag_miss_reason_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if int(row.get("rag_hit_count") or 0) > 0:
            continue
        for error in row.get("answerable_errors") or row.get("errors") or ["rag_empty"]:
            reason = _normalize_reason(error)
            if reason in {"answerable_rag_miss", "rag_miss"}:
                reason = "rag_empty"
            _inc(counts, reason)
    return counts


def _normalize_reason(error: object) -> str:
    text = str(error or "")
    mapping = {
        "answerable_rag_miss": "rag_empty",
        "rag_miss": "rag_empty",
        "answer_not_generated": "empty_answer",
        "answerable_fallback": "no_rag_domain",
    }
    return mapping.get(text, text)


def _merge_shop_payloads(payloads: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for payload in payloads:
        results.extend(list(payload.get("results") or []))
    merged = _aggregate_results(results, args, status="passed")
    if any(payload.get("status") == "failed" for payload in payloads):
        merged["status"] = "failed"
    shops_total = len(payloads)
    shops_with_candidates = sum(1 for payload in payloads if int(payload.get("selected_total") or payload.get("answerable_total") or 0) > 0)
    shops_replayed = sum(1 for payload in payloads if int(payload.get("total") or 0) > 0)
    per_shop_status: dict[str, str] = {}
    per_shop_selected_total: dict[str, int] = {}
    per_shop_pass_rate: dict[str, float] = {}
    per_shop_unclear_rate: dict[str, float] = {}
    per_shop_domain_counts: dict[str, dict[str, int]] = {}
    for payload in payloads:
        shop_hash = _first_result_shop_hash(payload) or f"shop-{len(per_shop_status) + 1}"
        per_shop_status[shop_hash] = str(payload.get("status") or "")
        per_shop_selected_total[shop_hash] = int(payload.get("selected_total") or payload.get("answerable_total") or 0)
        per_shop_pass_rate[shop_hash] = float(payload.get("answerable_pass_rate") or payload.get("pass_rate") or 0.0)
        per_shop_unclear_rate[shop_hash] = float(payload.get("unclear_rate") or 0.0)
        per_shop_domain_counts[shop_hash] = dict(payload.get("selected_by_domain") or payload.get("answerable_by_domain") or {})
    merged.update(
        {
            "shops_total": shops_total,
            "shops_with_candidates": shops_with_candidates,
            "shops_replayed": shops_replayed,
            "per_shop_status": per_shop_status,
            "per_shop_selected_total": per_shop_selected_total,
            "per_shop_pass_rate": per_shop_pass_rate,
            "per_shop_unclear_rate": per_shop_unclear_rate,
            "per_shop_domain_counts": per_shop_domain_counts,
            "selected_total": sum(int(payload.get("selected_total") or 0) for payload in payloads),
            "scanned_total": sum(int(payload.get("scanned_total") or 0) for payload in payloads),
            "candidate_total": sum(int(payload.get("candidate_total") or 0) for payload in payloads),
            "excluded_by_reason": _merge_count_dicts(payload.get("excluded_by_reason") for payload in payloads),
            "selected_by_domain": _merge_count_dicts(payload.get("selected_by_domain") for payload in payloads),
            "benchmark_case_count": sum(int(payload.get("benchmark_case_count") or 0) for payload in payloads),
            "benchmark_replayed_count": sum(int(payload.get("benchmark_replayed_count") or 0) for payload in payloads),
            "benchmark_message_not_found_count": sum(int(payload.get("benchmark_message_not_found_count") or 0) for payload in payloads),
            "benchmark_passed": sum(int(payload.get("benchmark_passed") or 0) for payload in payloads),
            "benchmark_failed": sum(int(payload.get("benchmark_failed") or 0) for payload in payloads),
            "benchmark_unclear": sum(int(payload.get("benchmark_unclear") or 0) for payload in payloads),
        }
    )
    if int(merged.get("benchmark_case_count") or 0):
        merged["benchmark_pass_rate"] = _rate(int(merged.get("benchmark_passed") or 0), int(merged.get("benchmark_case_count") or 0))
    if int(getattr(args, "require_min_shops", 0) or 0) and shops_with_candidates < int(getattr(args, "require_min_shops", 0) or 0):
        merged["status"] = "failed"
    if shops_with_candidates < shops_total and not bool(getattr(args, "allow_empty_shop", False)):
        merged["status"] = "failed"
    return merged


def _first_result_shop_hash(payload: Mapping[str, Any]) -> str:
    for row in payload.get("results") or []:
        if row.get("shop_id_hash"):
            return str(row.get("shop_id_hash"))
    shop_counts = payload.get("shop_counts") or {}
    if isinstance(shop_counts, Mapping) and shop_counts:
        return str(next(iter(shop_counts.keys())))
    return ""


def _merge_count_dicts(items: Iterable[Any]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        for key, value in item.items():
            merged[str(key)] = merged.get(str(key), 0) + int(value or 0)
    return merged


def _is_short_ack(content: str) -> bool:
    return content.strip() in SHORT_ACKS


def _is_media_only(content: str) -> bool:
    text = content.strip()
    return text in MEDIA_ONLY_MARKERS or text.lower() in MEDIA_ONLY_MARKERS


def _is_system_like(content: str) -> bool:
    text = content.strip().lower()
    return text.startswith(("系统", "system:", "assistant:", "客服:"))


def _validate_real_args(args: argparse.Namespace) -> str:
    if bool(getattr(args, "real_rag", False)):
        if not str(getattr(args, "pg_dsn", "") or "").strip():
            return "missing_pg_dsn"
        if not str(getattr(args, "ollama_base_url", "") or "").strip():
            return "missing_ollama_base_url"
        if not str(getattr(args, "embedding_model", "") or "").strip():
            return "missing_embedding_model"
    if bool(getattr(args, "real_llm", False)):
        if not str(getattr(args, "llm_base_url", "") or "").strip():
            return "missing_llm_base_url"
        if not str(getattr(args, "llm_model", "") or "").strip():
            return "missing_llm_model"
        if not str(getattr(args, "llm_api_key_env", "") or "").strip():
            return "missing_llm_api_key_env"
    return ""


def _error_payload(error_type: str) -> dict[str, Any]:
    return {
        "status": "error",
        "total": 0,
        "replayed": 0,
        "skipped": 0,
        "passed": 0,
        "failed": 1,
        "unclear": 0,
        **NO_SEND_FLAGS,
        "calls_llm": False,
        "calls_ollama": False,
        "connects_pgvector": False,
        "error_type": error_type,
        "results": [],
    }


def _missing_payload(path: Path) -> dict[str, Any]:
    del path
    return {
        "status": "missing",
        "total": 0,
        "replayed": 0,
        "skipped": 0,
        "passed": 0,
        "failed": 0,
        "unclear": 1,
        **NO_SEND_FLAGS,
        "calls_llm": False,
        "calls_ollama": False,
        "connects_pgvector": False,
        "error_type": "missing_db",
        "results": [],
    }


def _missing_table_payload(status: str, path: Path) -> dict[str, Any]:
    del path
    return {
        "status": status,
        "total": 0,
        "replayed": 0,
        "skipped": 0,
        "passed": 0,
        "failed": 0,
        "unclear": 1,
        **NO_SEND_FLAGS,
        "calls_llm": False,
        "calls_ollama": False,
        "connects_pgvector": False,
        "error_type": status,
        "results": [],
    }


def _first_existing_table(conn: sqlite3.Connection, candidates: Sequence[str]) -> str:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    existing = {str(row[0]) for row in rows}
    for candidate in candidates:
        if candidate in existing:
            return candidate
    return ""


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not table:
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _first_field(columns: set[str], candidates: Sequence[str]) -> str:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return ""


def _row_text(row: sqlite3.Row, fields: Sequence[str]) -> str:
    keys = set(row.keys())
    for field in fields:
        if field in keys and row[field] is not None:
            return str(row[field])
    return ""


def _row_pending_human(row: sqlite3.Row) -> bool:
    pending_value = _row_text(row, ("pending_human", "is_pending_human")).lower()
    if pending_value in {"1", "true", "yes"}:
        return True
    state = _row_text(row, ("human_state", "status")).lower()
    return state in {"pending_human", "human", "manual", "transferred"}


def _guardrail_status(result: WorkflowResult) -> str:
    trace = result.trace if isinstance(result.trace, dict) else {}
    status = str(trace.get("guardrail_status") or "")
    if status:
        return status
    if "guardrail_blocked" in result.risk_flags:
        return "blocked"
    return "safe"


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "")
        if not text:
            continue
        counts[text] = counts.get(text, 0) + 1
    return counts


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def write_json(payload: Mapping[str, Any], *, json_only: bool) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if not json_only:
        print("internal_conversation_replay: no-send summary")
    print(rendered)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_replay(args)
    write_json(payload, json_only=bool(getattr(args, "json_only", False)))
    return 1 if payload.get("status") in {"error", "failed"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
