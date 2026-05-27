"""Interactive no-send live chat helper for InternalWorkflowEngine.

This script is for local manual testing only. It never imports channel senders,
FastGPT clients, queue workers, or runtime message send paths. Conversation
history is kept in process memory and is not written to SQLite or artifacts.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import Session.session_manager  # noqa: F401  # Import order avoids existing logger circular import.
from Message.workflow.answer_generator import OpenAICompatibleAnswerGenerator
from Message.workflow.conversation_context import (
    ConversationContext,
    ConversationMessage,
    ConversationRecord,
    conversation_id,
    stable_hash,
    summarize_content,
)
from Message.workflow.embedding_client import OllamaBgeM3EmbeddingClient
from Message.workflow.internal_engine import InternalWorkflowEngine
from Message.workflow.knowledge_repository import ProductKnowledgeRepository
from Message.workflow.rag_retriever import VectorStoreRAGRetriever
from Message.workflow.sop_provider import SOPProvider
from Message.workflow.types import WorkflowContext, WorkflowResult, action_value
from Message.workflow.vector_store import PgVectorStore


DEFAULT_SOP_FILE = REPO_ROOT / "docs" / "acceptance" / "fixtures" / "internal_sop_example.md"
NO_SEND_FLAGS = {
    "no_send": True,
    "calls_fastgpt": False,
    "sends_pdd": False,
}
PRODUCT_DOMAINS = {"product_basic", "product_catalog"}
EXIT_WORDS = {"exit", "quit", "q", "\u9000\u51fa"}
MANUAL_BUYER_ID = "manual-live-buyer"
MANUAL_SESSION_ID = "manual-live-session"


@dataclass
class LiveHistoryRepository:
    """Mutable in-memory history for one manual live-chat process."""

    max_window: int = 6
    records: list[ConversationRecord] = field(default_factory=list)

    def append(
        self,
        *,
        shop_id: str,
        buyer_id: str,
        session_id: str,
        role: str,
        content: str,
        intent: str = "",
        action: str = "",
    ) -> None:
        self.records.append(
            ConversationRecord(
                shop_id=str(shop_id or ""),
                user_id="",
                buyer_id=str(buyer_id or ""),
                session_id=str(session_id or ""),
                role=str(role or ""),
                message_type="text",
                content=str(content or ""),
                created_at=datetime.now(timezone.utc).isoformat(),
                source="internal_live_chat",
                intent=str(intent or ""),
                action=str(action or ""),
            )
        )

    def load_context(
        self,
        *,
        shop_id: str,
        user_id: str,
        buyer_id: str,
        session_id: str,
        limit: int = 6,
    ) -> ConversationContext:
        del limit
        matched = [
            record
            for record in self.records
            if record.shop_id == str(shop_id or "")
            and record.user_id == str(user_id or "")
            and record.buyer_id == str(buyer_id or "")
            and record.session_id == str(session_id or "")
        ]
        window_records = matched[-max(0, int(self.max_window or 0)) :] if self.max_window else []
        window = tuple(_message_from_record(record) for record in window_records)
        last_record = matched[-1] if matched else None
        return ConversationContext(
            shop_id=str(shop_id or ""),
            user_id=str(user_id or ""),
            buyer_id=str(buyer_id or ""),
            session_id=str(session_id or ""),
            conversation_id=conversation_id(shop_id, user_id, buyer_id, session_id),
            recent_messages=window,
            history_window=window,
            history_message_count=len(matched),
            last_intent=last_record.intent if last_record else "",
            last_action=last_record.action if last_record else "",
            history_source="internal_live_chat_memory",
        )


class LiveRAGRetriever:
    def __init__(
        self,
        *,
        embedding_client: Any,
        vector_store: Any,
        shop_id: str,
        product_version: str,
        sop_version: str,
        top_k: int,
    ) -> None:
        self.embedding_client = embedding_client
        self.vector_store = vector_store
        self.shop_id = str(shop_id or "").strip()
        self.product_version = str(product_version or "").strip()
        self.sop_version = str(sop_version or "").strip()
        self.top_k = max(1, int(top_k or 3))
        self._last_stats: dict[str, Any] = {}

    def retrieve(self, context: Any, intent: str, domain: str, query: str, top_k: int = 3):
        version = self.product_version if str(domain or "") in PRODUCT_DOMAINS else self.sop_version
        delegate = VectorStoreRAGRetriever(
            embedding_client=self.embedding_client,
            vector_store=self.vector_store,
            version=version,
            top_k=self.top_k,
        )
        proxy_context = SimpleNamespace(shop_id=self.shop_id or str(getattr(context, "shop_id", "") or ""))
        hits = delegate.retrieve(proxy_context, intent, domain, query, top_k=max(1, int(top_k or self.top_k)))
        self._last_stats = delegate.get_last_stats()
        return hits

    def get_last_stats(self) -> dict[str, Any]:
        return dict(self._last_stats)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run InternalWorkflowEngine as an interactive no-send live chat.")
    parser.add_argument("--shop-id", default="", help="Shop id to scope RAG and workflow context.")
    parser.add_argument("--pg-dsn", default="", help="PostgreSQL/pgvector DSN. Never printed.")
    parser.add_argument("--ollama-base-url", default="", help="Ollama base URL.")
    parser.add_argument("--embedding-model", default="", help="Embedding model name.")
    parser.add_argument("--llm-base-url", default="", help="OpenAI-compatible LLM base URL.")
    parser.add_argument("--llm-model", default="", help="OpenAI-compatible LLM model.")
    parser.add_argument("--llm-api-key-env", default="AI_WORKFLOW_LLM_API_KEY", help="Environment variable containing the LLM API key.")
    parser.add_argument("--product-version", default="real-product-v1", help="RAG version for product domains.")
    parser.add_argument("--sop-version", default="sop-test-v1", help="RAG version for SOP domains.")
    parser.add_argument("--rag-top-k", type=int, default=3, help="RAG retrieval limit.")
    parser.add_argument("--history-window", type=int, default=6, help="In-memory history window size.")
    parser.add_argument("--check-config", action="store_true", help="Validate explicit config and exit without external calls.")
    parser.add_argument("--json-only", action="store_true", help="For --check-config, print JSON only.")
    return parser.parse_args(argv)


def build_engine(args: argparse.Namespace, history_repository: LiveHistoryRepository) -> InternalWorkflowEngine:
    _validate_required_config(args, require_api_key=True)
    rag_retriever = LiveRAGRetriever(
        embedding_client=OllamaBgeM3EmbeddingClient(
            base_url=str(args.ollama_base_url or ""),
            model=str(args.embedding_model or ""),
        ),
        vector_store=PgVectorStore(str(args.pg_dsn or "")),
        shop_id=str(args.shop_id or ""),
        product_version=str(args.product_version or "real-product-v1"),
        sop_version=str(args.sop_version or "sop-test-v1"),
        top_k=max(1, int(args.rag_top_k or 3)),
    )
    answer_generator = OpenAICompatibleAnswerGenerator(
        base_url=str(args.llm_base_url or ""),
        model=str(args.llm_model or ""),
        api_key_env=str(args.llm_api_key_env or "AI_WORKFLOW_LLM_API_KEY"),
    )
    sop_provider = SOPProvider.from_markdown_file(DEFAULT_SOP_FILE) if DEFAULT_SOP_FILE.exists() else None
    return InternalWorkflowEngine(
        knowledge_repository=ProductKnowledgeRepository(records_source=[]),
        sop_provider=sop_provider,
        conversation_context_repository=history_repository,
        answer_generator=answer_generator,
        rag_retriever=rag_retriever,
    )


async def run_turn(
    engine: InternalWorkflowEngine,
    history_repository: LiveHistoryRepository,
    args: argparse.Namespace,
    *,
    user_text: str,
    turn_index: int,
) -> WorkflowResult:
    buyer_id = MANUAL_BUYER_ID
    session_id = MANUAL_SESSION_ID
    context = WorkflowContext(
        trace_id=f"internal-live-{turn_index}-{stable_hash(user_text)}",
        shop_id=str(args.shop_id or ""),
        user_id="",
        customer_uid=buyer_id,
        buyer_id=buyer_id,
        session_id=session_id,
        chat_id=session_id,
        message_type="text",
        content=str(user_text or ""),
        metadata={
            "source": "internal_live_chat",
            "no_send": True,
            "no_db_write": True,
            "product_version": str(args.product_version or "real-product-v1"),
            "sop_version": str(args.sop_version or "sop-test-v1"),
        },
    )
    result = await engine.run(context)
    action = action_value(result.action)
    history_repository.append(
        shop_id=str(args.shop_id or ""),
        buyer_id=buyer_id,
        session_id=session_id,
        role="buyer",
        content=user_text,
        intent=str(result.intent or ""),
        action=action,
    )
    if result.reply_text:
        history_repository.append(
            shop_id=str(args.shop_id or ""),
            buyer_id=buyer_id,
            session_id=session_id,
            role="assistant",
            content=result.reply_text,
            intent=str(result.intent or ""),
            action=action,
        )
    return result


def interactive_loop(args: argparse.Namespace) -> int:
    try:
        _validate_required_config(args, require_api_key=True)
    except ValueError as exc:
        print(f"配置错误: {exc}")
        return 1

    history_repository = LiveHistoryRepository(max_window=max(0, int(args.history_window or 6)))
    engine = build_engine(args, history_repository)
    print("Internal live chat no-send mode. 输入买家消息，输入 exit 退出。")
    turn_index = 1
    while True:
        try:
            user_text = input("buyer> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_text:
            continue
        if user_text.lower() in EXIT_WORDS:
            break
        try:
            result = asyncio.run(
                run_turn(
                    engine,
                    history_repository,
                    args,
                    user_text=user_text,
                    turn_index=turn_index,
                )
            )
        except Exception as exc:  # pragma: no cover - manual safety net.
            print(f"error: {type(exc).__name__}")
            turn_index += 1
            continue
        print(_format_turn_output(result))
        turn_index += 1
    return 0


def config_summary(args: argparse.Namespace) -> dict[str, Any]:
    try:
        _validate_required_config(args, require_api_key=True)
    except ValueError as exc:
        return {
            "status": "error",
            "error_type": "missing_required_args",
            "error_summary": _sanitize_error(str(exc)),
            **NO_SEND_FLAGS,
            "calls_llm": False,
            "calls_ollama": False,
            "connects_pgvector": False,
        }
    return {
        "status": "ok",
        "shop_id_hash": stable_hash(args.shop_id),
        "product_version": str(args.product_version or "real-product-v1"),
        "sop_version": str(args.sop_version or "sop-test-v1"),
        "rag_top_k": max(1, int(args.rag_top_k or 3)),
        "history_window": max(0, int(args.history_window or 6)),
        "llm_model": str(args.llm_model or ""),
        "llm_api_key_env": str(args.llm_api_key_env or ""),
        **NO_SEND_FLAGS,
        "calls_llm": False,
        "calls_ollama": False,
        "connects_pgvector": False,
    }


def write_json(payload: Mapping[str, Any], *, json_only: bool) -> None:
    if not json_only:
        print("internal_live_chat: no-send config summary")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _validate_required_config(args: argparse.Namespace, *, require_api_key: bool) -> None:
    missing = []
    for attr, flag in (
        ("shop_id", "--shop-id"),
        ("pg_dsn", "--pg-dsn"),
        ("ollama_base_url", "--ollama-base-url"),
        ("embedding_model", "--embedding-model"),
        ("llm_base_url", "--llm-base-url"),
        ("llm_model", "--llm-model"),
        ("llm_api_key_env", "--llm-api-key-env"),
    ):
        if not str(getattr(args, attr, "") or "").strip():
            missing.append(flag)
    key_env = str(getattr(args, "llm_api_key_env", "") or "").strip()
    if require_api_key and key_env and not os.getenv(key_env):
        missing.append(f"env:{key_env}")
    if missing:
        raise ValueError("missing " + ", ".join(missing))


def _format_turn_output(result: WorkflowResult) -> str:
    trace = result.trace if isinstance(result.trace, dict) else {}
    action = action_value(result.action)
    guardrail_status = _guardrail_status(result)
    lines = [
        f"action: {action}",
        f"intent: {result.intent or ''}",
        f"rag_status: {trace.get('rag_status') or 'disabled'}",
        f"rag_hit_count: {int(trace.get('rag_hit_count') or 0)}",
        f"guardrail_status: {guardrail_status}",
        f"answer_generation_status: {trace.get('answer_generation_status') or ''}",
    ]
    reply_text = str(result.reply_text or "")
    if guardrail_status == "blocked":
        lines.append("final_reply: 已拦截，建议转人工处理。")
    elif action == "transfer_human":
        lines.append("final_reply: 已转人工处理。")
    elif reply_text:
        lines.append("final_reply:")
        lines.append(reply_text)
    else:
        reason = str(result.reason or trace.get("fallback_reason") or trace.get("reason") or "")
        lines.append(f"fallback_reason: {reason}")
        lines.append("final_reply: 当前无法直接生成安全回复，建议转人工确认。")
    return "\n".join(lines)


def _guardrail_status(result: WorkflowResult) -> str:
    trace = result.trace if isinstance(result.trace, dict) else {}
    status = str(trace.get("guardrail_status") or "")
    if status:
        return status
    if "guardrail_blocked" in result.risk_flags:
        return "blocked"
    return "safe"


def _message_from_record(record: ConversationRecord) -> ConversationMessage:
    return ConversationMessage(
        role=record.role,
        message_type=record.message_type,
        content=record.content,
        content_summary=summarize_content(record.content),
        content_hash=stable_hash(record.content),
        created_at=record.created_at,
        source=record.source,
    )


def _sanitize_error(value: str) -> str:
    text = str(value or "")
    for sensitive in ("postgresql://", "postgres://"):
        if sensitive in text:
            return "missing required explicit configuration"
    return text


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if bool(args.check_config):
        payload = config_summary(args)
        write_json(payload, json_only=bool(args.json_only))
        return 1 if payload.get("status") == "error" else 0
    return interactive_loop(args)


if __name__ == "__main__":
    raise SystemExit(main())
