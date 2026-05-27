"""Offline synthetic QA runner for InternalWorkflowEngine.

This runner exercises only the deterministic internal workflow engine with
synthetic records. It does not import platform senders, channel runtime, DB
repositories, or network-backed AI providers.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import Session.session_manager  # Import order avoids existing core/logger circular import.
from Message.workflow.answer_generator import FakeAnswerGenerator
from Message.workflow.internal_engine import InternalWorkflowEngine
from Message.workflow.knowledge_repository import ProductKnowledgeRepository
from Message.workflow.rag_retriever import InMemoryRAGRetriever
from Message.workflow.rag_types import KnowledgeChunk
from Message.workflow.sop_provider import SOPProvider
from Message.workflow.types import WorkflowContext, action_value
from scripts.acceptance.internal_engine_cases import (
    SyntheticCase,
    default_cases,
    load_sop_fixture_summary,
    sop_domain_cases,
    synthetic_product_records,
)


SOP_DOMAINS = {
    "logistics_policy",
    "after_sales_evidence",
    "promotion_policy",
    "redline_escalation",
    "sensitive_user_safety",
}


def build_engine(
    *,
    sop_file: Path | str | None = None,
    use_fake_answer_generator: bool = False,
    use_fake_rag: bool = False,
) -> InternalWorkflowEngine:
    sop_provider = SOPProvider.from_markdown_file(sop_file) if sop_file else None
    return InternalWorkflowEngine(
        knowledge_repository=ProductKnowledgeRepository(records_source=lambda _shop_id: synthetic_product_records()),
        sop_provider=sop_provider,
        answer_generator=FakeAnswerGenerator() if use_fake_answer_generator else None,
        rag_retriever=_fake_rag_retriever() if use_fake_rag else None,
    )


def _fake_rag_retriever() -> InMemoryRAGRetriever:
    return InMemoryRAGRetriever(
        [
            KnowledgeChunk(
                chunk_id="synthetic-rag-logistics",
                shop_id="synthetic-shop-1",
                domain="logistics_policy",
                source_type="synthetic_rag",
                source_id="synthetic-rag-logistics",
                title="synthetic logistics policy",
                content="synthetic safe RAG content",
                version="rag-synthetic-v1",
            )
        ]
    )


def build_context(case: SyntheticCase, *, sop_summary: dict[str, Any] | None = None) -> WorkflowContext:
    metadata = {"source": "synthetic_internal_engine_qa"}
    if sop_summary:
        metadata.update(sop_summary)
    return WorkflowContext(
        trace_id=f"synthetic-trace-{case.case_id}",
        shop_id=case.shop_id,
        user_id="synthetic-user",
        customer_uid="synthetic-customer",
        buyer_id="synthetic-buyer",
        session_id=f"synthetic-session-{case.case_id}",
        chat_id=f"synthetic-chat-{case.case_id}",
        dataset_id="synthetic-dataset",
        message_type="text",
        content=case.question,
        goods_context=case.goods_context,
        metadata=metadata,
    )


async def _run_one(
    engine: InternalWorkflowEngine,
    case: SyntheticCase,
    *,
    sop_summary: dict[str, Any] | None = None,
    use_fake_answer_generator: bool = False,
    use_fake_rag: bool = False,
) -> dict[str, Any]:
    result = await engine.run(build_context(case, sop_summary=sop_summary))
    actual_action = action_value(result.action)
    failures = []
    generated_fallback_reply = (
        use_fake_answer_generator
        and case.expected_action == "fallback"
        and result.intent == "fallback"
        and actual_action == "reply"
    )

    if actual_action != case.expected_action and not generated_fallback_reply:
        failures.append(f"action expected {case.expected_action!r}, got {actual_action!r}")
    if result.intent != case.expected_intent:
        failures.append(f"intent expected {case.expected_intent!r}, got {result.intent!r}")
    if case.expected_reason and result.reason != case.expected_reason and not use_fake_answer_generator and not use_fake_rag:
        failures.append(f"reason expected {case.expected_reason!r}, got {result.reason!r}")
    if case.expect_reply is True and not result.reply_text:
        failures.append("reply_text expected to be present")
    if case.expect_reply is False and result.reply_text and not generated_fallback_reply:
        failures.append("reply_text expected to be empty")
    if case.expect_knowledge_refs is True and not result.knowledge_refs:
        failures.append("knowledge_refs expected to be present")
    if case.expect_knowledge_refs is False and result.knowledge_refs:
        failures.append("knowledge_refs expected to be empty")

    knowledge_source = _knowledge_source(result.knowledge_refs)
    sop_domain = _sop_domain(result.knowledge_refs, result.trace)
    sop_version = _sop_version(result.trace, sop_summary)
    sop_hit = knowledge_source == "sop" and bool(sop_domain)

    if case.expected_knowledge_source and knowledge_source != case.expected_knowledge_source and not use_fake_rag:
        failures.append(f"knowledge_source expected {case.expected_knowledge_source!r}, got {knowledge_source!r}")
    if case.expected_sop_domain and sop_domain != case.expected_sop_domain:
        failures.append(f"sop_domain expected {case.expected_sop_domain!r}, got {sop_domain!r}")

    reply_text = result.reply_text or ""
    leaked_phrases = [phrase for phrase in case.forbidden_phrases if phrase and phrase in reply_text]
    if leaked_phrases:
        failures.append(f"reply_text contains forbidden phrases: {', '.join(leaked_phrases)}")

    if not failures:
        status = "passed"
    elif case.required:
        status = "failed"
    else:
        status = "unclear"

    return {
        "case_id": case.case_id,
        "category": case.category,
        "priority": case.priority,
        "required": case.required,
        "status": status,
        "content_length": len(case.question),
        "content_hash": _short_hash(case.question),
        "expected_action": case.expected_action,
        "actual_action": actual_action,
        "expected_intent": case.expected_intent,
        "actual_intent": result.intent,
        "actual_reason": result.reason,
        "reply_present": bool(result.reply_text),
        "reply_length": len(reply_text),
        "reply_hash": _short_hash(reply_text) if reply_text else "",
        "risk_flags": list(result.risk_flags),
        "action": actual_action,
        "intent": result.intent,
        "knowledge_hit_count": len(result.knowledge_refs),
        "knowledge_source": knowledge_source,
        "knowledge_ref_count": len(result.knowledge_refs),
        "sop_hit": sop_hit,
        "sop_domain": sop_domain,
        "sop_version": sop_version,
        "history_message_count": int(result.trace.get("history_message_count") or 0),
        "history_window_size": int(result.trace.get("history_window_size") or 0),
        "pending_human": bool(result.trace.get("pending_human") or False),
        "answer_generator": str(result.trace.get("answer_generator") or ("fake" if use_fake_answer_generator else "")),
        "answer_generation_source": str(result.trace.get("answer_generation_source") or ""),
        "answer_confidence": result.trace.get("answer_confidence", 0.0),
        "used_history_count": int(result.trace.get("used_history_count") or 0),
        "prompt_hash": str(result.trace.get("prompt_hash") or ""),
        "guardrail_status": _guardrail_status(result),
        "rag_enabled": bool(result.trace.get("rag_enabled", False)),
        "rag_status": str(result.trace.get("rag_status") or "disabled"),
        "rag_hit_count": int(result.trace.get("rag_hit_count") or 0),
        "rag_domains": list(result.trace.get("rag_domains") or []),
        "rag_top_score": result.trace.get("rag_top_score", 0.0),
        "retrieval_source": str(result.trace.get("retrieval_source") or ""),
        "failures": failures,
    }


async def _run_all(
    cases: Sequence[SyntheticCase],
    *,
    sop_summary: dict[str, Any],
    use_fake_answer_generator: bool = False,
    use_fake_rag: bool = False,
) -> list[dict[str, Any]]:
    base_engine = build_engine(use_fake_answer_generator=use_fake_answer_generator, use_fake_rag=use_fake_rag)
    sop_engine = (
        build_engine(
            sop_file=sop_summary.get("_sop_file"),
            use_fake_answer_generator=use_fake_answer_generator,
            use_fake_rag=use_fake_rag,
        )
        if sop_summary.get("_sop_file")
        else None
    )
    rows = []
    for case in cases:
        engine = sop_engine if case.expected_sop_domain and sop_engine is not None else base_engine
        rows.append(
            await _run_one(
                engine,
                case,
                sop_summary=sop_summary,
                use_fake_answer_generator=use_fake_answer_generator,
                use_fake_rag=use_fake_rag,
            )
        )
    return rows


def run_cases(
    cases: Iterable[SyntheticCase] | None = None,
    *,
    limit: int | None = None,
    sop_file: Path | str | None = None,
    use_fake_answer_generator: bool = False,
    use_fake_rag: bool = False,
) -> dict[str, Any]:
    selected = list(cases if cases is not None else default_cases())
    if cases is None and sop_file:
        selected.extend(sop_domain_cases())
    if limit is not None:
        selected = selected[: max(0, limit)]

    sop_summary = load_sop_fixture_summary(sop_file)
    if sop_file:
        sop_summary["_sop_file"] = str(sop_file)
    rows = asyncio.run(
        _run_all(
            selected,
            sop_summary=sop_summary,
            use_fake_answer_generator=use_fake_answer_generator,
            use_fake_rag=use_fake_rag,
        )
    )
    summary = {
        "total": len(rows),
        "passed": sum(1 for row in rows if row["status"] == "passed"),
        "failed": sum(1 for row in rows if row["status"] == "failed"),
        "unclear": sum(1 for row in rows if row["status"] == "unclear"),
    }
    return {
        "runner": "internal_engine_synthetic_qa",
        "engine": "InternalWorkflowEngine",
        "dry_run": False,
        **{key: value for key, value in sop_summary.items() if key != "_sop_file"},
        "summary": summary,
        "offline_constraints": {
            "uses_synthetic_data_only": True,
            "uses_db": False,
            "calls_fastgpt": False,
            "calls_llm": False,
            "calls_pdd": False,
            "sends_messages": False,
        },
        "answer_generator": "fake" if use_fake_answer_generator else "",
        "rag_enabled": bool(use_fake_rag),
        "cases": rows,
    }


def dry_run_cases(
    cases: Iterable[SyntheticCase] | None = None,
    *,
    limit: int | None = None,
    sop_file: Path | str | None = None,
    use_fake_answer_generator: bool = False,
    use_fake_rag: bool = False,
) -> dict[str, Any]:
    selected = list(cases if cases is not None else default_cases())
    if cases is None and sop_file:
        selected.extend(sop_domain_cases())
    if limit is not None:
        selected = selected[: max(0, limit)]

    sop_summary = load_sop_fixture_summary(sop_file)
    rows = [
        {
            "case_id": case.case_id,
            "category": case.category,
            "priority": case.priority,
            "required": case.required,
            "content_length": len(case.question),
            "content_hash": _short_hash(case.question),
            "expected_action": case.expected_action,
            "expected_intent": case.expected_intent,
            "expected_reason": case.expected_reason,
            "expected_knowledge_source": case.expected_knowledge_source,
            "expected_sop_domain": case.expected_sop_domain,
            "has_goods_context": bool(case.goods_context),
            "history_message_count": 0,
            "history_window_size": 0,
            "pending_human": False,
            "answer_generator": "fake" if use_fake_answer_generator else "",
            "answer_generation_source": "",
            "answer_confidence": 0.0,
            "used_history_count": 0,
            "prompt_hash": "",
            "guardrail_status": "",
            "rag_enabled": bool(use_fake_rag),
            "rag_status": "not_executed" if use_fake_rag else "disabled",
            "rag_hit_count": 0,
            "rag_domains": [],
            "rag_top_score": 0.0,
            "retrieval_source": "",
        }
        for case in selected
    ]
    return {
        "runner": "internal_engine_synthetic_qa",
        "engine": "InternalWorkflowEngine",
        "dry_run": True,
        **sop_summary,
        "summary": {
            "total": len(rows),
            "passed": 0,
            "failed": 0,
            "unclear": 0,
        },
        "offline_constraints": {
            "uses_synthetic_data_only": True,
            "uses_db": False,
            "calls_fastgpt": False,
            "calls_llm": False,
            "calls_pdd": False,
            "sends_messages": False,
        },
        "answer_generator": "fake" if use_fake_answer_generator else "",
        "rag_enabled": bool(use_fake_rag),
        "cases": rows,
    }


def write_report_and_exit(
    report: dict[str, Any],
    *,
    output_path: Path | None = None,
    json_only: bool = False,
) -> int:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")

    if json_only:
        if not output_path:
            print(rendered)
    else:
        summary = report["summary"]
        print(
            "internal_engine_synthetic_qa: "
            f"passed={summary['passed']} failed={summary['failed']} unclear={summary['unclear']} total={summary['total']}"
        )
        if output_path:
            print(f"report={output_path}")
        else:
            print(rendered)

    return 1 if report["summary"]["failed"] else 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run offline synthetic QA for InternalWorkflowEngine.")
    parser.add_argument("--output", type=Path, help="Write JSON report to this path.")
    parser.add_argument("--limit", type=int, help="Run at most this many synthetic cases.")
    parser.add_argument("--sop-file", type=Path, help="Optional reviewed SOP Markdown fixture to summarize.")
    parser.add_argument("--json-only", action="store_true", help="Suppress human summary output.")
    parser.add_argument("--dry-run", action="store_true", help="List synthetic cases without executing the engine.")
    parser.add_argument("--use-fake-answer-generator", action="store_true", help="Use offline fake answer generator.")
    parser.add_argument("--use-fake-rag", action="store_true", help="Use offline in-memory RAG hits.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = (
        dry_run_cases(
            limit=args.limit,
            sop_file=args.sop_file,
            use_fake_answer_generator=args.use_fake_answer_generator,
            use_fake_rag=args.use_fake_rag,
        )
        if args.dry_run
        else run_cases(
            limit=args.limit,
            sop_file=args.sop_file,
            use_fake_answer_generator=args.use_fake_answer_generator,
            use_fake_rag=args.use_fake_rag,
        )
    )
    return write_report_and_exit(report, output_path=args.output, json_only=args.json_only)


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _knowledge_source(refs: list[dict[str, Any]]) -> str:
    if not refs:
        return ""
    first = refs[0]
    domain = _normalize_sop_domain(str(first.get("domain") or ""))
    source = str(first.get("source") or "")
    if source == "rag":
        return "rag"
    if domain in SOP_DOMAINS:
        return "sop"
    return source


def _sop_domain(refs: list[dict[str, Any]], trace: dict[str, Any]) -> str:
    for ref in refs:
        domain = _normalize_sop_domain(str(ref.get("domain") or ""))
        if domain in SOP_DOMAINS:
            return domain

    domains = trace.get("sop_domains") if isinstance(trace, dict) else []
    if isinstance(domains, list):
        for domain in domains:
            normalized = _normalize_sop_domain(str(domain or ""))
            if normalized in SOP_DOMAINS:
                return normalized
    return ""


def _sop_version(trace: dict[str, Any], sop_summary: dict[str, Any] | None) -> str:
    if isinstance(sop_summary, dict):
        version = str(sop_summary.get("sop_version") or "").strip()
        if version:
            return version
    if isinstance(trace, dict):
        version = str(trace.get("sop_version") or "").strip()
        if version:
            return version
    return ""


def _normalize_sop_domain(domain: str) -> str:
    if domain == "after_sales_evidence_collection":
        return "after_sales_evidence"
    if domain == "logistics_order_status":
        return "logistics_policy"
    return domain


def _guardrail_status(result) -> str:
    if result.reason == "output_guardrail_policy_violation":
        return "blocked"
    if "policy_violation" in set(result.risk_flags or []):
        return "blocked"
    return "passed" if result.reply_text else ""

if __name__ == "__main__":
    raise SystemExit(main())
