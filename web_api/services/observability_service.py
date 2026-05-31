from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from web_api.services.sqlite_readonly import ReadOnlySqlite, parse_json_object


RETRYABLE_FAILURE_STATUSES = {
    "reply_send_failed",
    "transfer_send_failed",
    "reply_delivery_unknown",
    "transfer_delivery_unknown",
}
FINAL_FAILURE_STATUSES = RETRYABLE_FAILURE_STATUSES | {
    "blocked_by_platform_policy",
    "suppressed_repeated_40013",
    "dead_letter",
    "pdd_sending_disabled",
}
SUCCESS_STATUSES = {"sent", "reply_sent"}
SUPPRESSED_STATUSES = {"suppressed_duplicate", "pdd_sending_disabled"}


class ObservabilityService:
    """Read-only buyer conversation observability over queue and trace data."""

    def __init__(self, db: ReadOnlySqlite | None = None) -> None:
        self.db = db or ReadOnlySqlite()

    def list_conversations(self, *, shop_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        rows = self._message_rows(shop_id=shop_id, limit=max(50, int(limit) * 10))
        conversations: dict[str, dict[str, Any]] = {}
        for row in rows:
            buyer_id = str(row.get("buyer_id") or "unknown")
            selected_shop_id = str(row.get("shop_id") or "")
            key = f"{selected_shop_id}|{buyer_id}"
            item = conversations.setdefault(
                key,
                {
                    "shop_id": selected_shop_id,
                    "buyer_id": buyer_id,
                    "session_id": str(row.get("session_id") or ""),
                    "last_message": "",
                    "last_send_text": "",
                    "last_status": "unknown",
                    "last_status_label": "未知",
                    "failed_count": 0,
                    "message_count": 0,
                    "last_trace_id": "",
                    "last_active_at": "",
                    "last_active_ts": 0.0,
                },
            )
            item["message_count"] += 1
            status = str(row.get("final_status") or row.get("outbox_status") or row.get("inbound_status") or "unknown")
            if self._is_attention_status(status):
                item["failed_count"] += 1
            ts = float(row.get("updated_at") or row.get("created_at") or 0)
            if ts >= float(item.get("last_active_ts") or 0):
                item.update(
                    {
                        "session_id": str(row.get("session_id") or item.get("session_id") or ""),
                        "last_message": str(row.get("buyer_message") or ""),
                        "last_send_text": str(row.get("send_text") or row.get("generated_reply") or ""),
                        "last_status": status,
                        "last_status_label": self._status_label(status),
                        "last_trace_id": str(row.get("trace_id") or ""),
                        "last_active_at": self._iso(ts),
                        "last_active_ts": ts,
                    }
                )

        items = sorted(conversations.values(), key=lambda item: float(item.get("last_active_ts") or 0), reverse=True)
        for item in items:
            item.pop("last_active_ts", None)
        return {"items": items[: max(1, int(limit))], "total": len(items), "warning": self._table_warning()}

    def list_messages(self, buyer_id: str, *, shop_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        rows = [
            row
            for row in self._message_rows(shop_id=shop_id, limit=max(100, int(limit) * 5))
            if str(row.get("buyer_id") or "") == str(buyer_id)
        ]
        rows = sorted(rows, key=lambda row: float(row.get("created_at") or row.get("updated_at") or 0))
        selected = rows[-max(1, int(limit)) :]
        return {"items": [self._hydrate_message(row) for row in selected], "total": len(rows)}

    def get_trace(self, trace_id: str) -> dict[str, Any]:
        rows = [row for row in self._message_rows(limit=1000) if str(row.get("trace_id") or "") == str(trace_id)]
        if not rows:
            return {"trace_id": trace_id, "events": {}, "nodes": [], "warning": "trace_not_found"}
        return self._hydrate_message(rows[-1])

    def _message_rows(self, *, shop_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        shop_filter = str(shop_id or "")
        inbound = self.db.query(
            """
            SELECT id, trace_id, shop_id, user_id, buyer_id, session_id, message_type,
                   payload_json, status, retry_count, error_type, created_at, updated_at
            FROM pdd_inbound_message_queue
            WHERE (? = '' OR shop_id = ?)
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (shop_filter, shop_filter, max(1, int(limit))),
            ("pdd_inbound_message_queue",),
        )
        outbox = self.db.query(
            """
            SELECT *
            FROM pdd_reply_outbox
            WHERE (? = '' OR shop_id = ?)
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (shop_filter, shop_filter, max(1, int(limit))),
            ("pdd_reply_outbox",),
        )

        outbox_by_inbound: dict[str, list[dict[str, Any]]] = {}
        for row in outbox.rows:
            outbox_by_inbound.setdefault(str(row.get("inbound_record_id") or ""), []).append(row)

        combined: list[dict[str, Any]] = []
        seen_outbox: set[str] = set()
        for row in inbound.rows:
            payload = parse_json_object(row.get("payload_json"))
            attached = sorted(
                outbox_by_inbound.get(str(row.get("id") or ""), []),
                key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0),
            )
            selected = attached[-1] if attached else {}
            if selected:
                seen_outbox.add(str(selected.get("id") or ""))
            combined.append(self._combine_row(row, payload, selected))

        for row in outbox.rows:
            row_id = str(row.get("id") or "")
            if row_id in seen_outbox:
                continue
            combined.append(self._combine_row({}, {}, row))

        return sorted(combined, key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0), reverse=True)

    def _combine_row(self, inbound: dict[str, Any], payload: dict[str, Any], outbox: dict[str, Any]) -> dict[str, Any]:
        trace_id = str(inbound.get("trace_id") or outbox.get("trace_id") or payload.get("trace_id") or "")
        buyer_message = str(payload.get("content") or "")
        generated_reply = str(outbox.get("reply_text") or "")
        status = str(outbox.get("status") or inbound.get("status") or "unknown")
        send_text = generated_reply if self._was_send_attempted(status) else ""
        created_at = float(inbound.get("created_at") or outbox.get("created_at") or 0)
        updated_at = float(outbox.get("updated_at") or inbound.get("updated_at") or created_at)
        return {
            "trace_id": trace_id,
            "inbound_id": str(inbound.get("id") or outbox.get("inbound_record_id") or ""),
            "outbox_id": str(outbox.get("id") or ""),
            "shop_id": str(inbound.get("shop_id") or outbox.get("shop_id") or payload.get("shop_id") or ""),
            "user_id": str(inbound.get("user_id") or outbox.get("user_id") or payload.get("user_id") or ""),
            "buyer_id": str(inbound.get("buyer_id") or outbox.get("buyer_id") or payload.get("from_uid") or ""),
            "session_id": str(inbound.get("session_id") or outbox.get("session_id") or payload.get("session_id") or ""),
            "message_type": str(inbound.get("message_type") or payload.get("message_type") or ""),
            "buyer_message": buyer_message,
            "generated_reply": generated_reply,
            "send_text": send_text,
            "inbound_status": str(inbound.get("status") or ""),
            "outbox_status": str(outbox.get("status") or ""),
            "final_status": status,
            "retry_count": int(outbox.get("retry_count") or 0),
            "max_retries": int(outbox.get("max_retries") or 0),
            "next_retry_at": self._iso(float(outbox.get("next_retry_at") or 0)),
            "last_attempt_at": self._iso(float(outbox.get("last_attempt_at") or 0)),
            "pdd_error_code": str(outbox.get("pdd_error_code") or ""),
            "reply_action": str(outbox.get("reply_action") or ""),
            "reply_source": str(outbox.get("reply_source") or ""),
            "reply_hash": str(outbox.get("reply_hash") or ""),
            "reply_length": int(outbox.get("reply_length") or len(generated_reply)),
            "error_summary_hash": str(outbox.get("error_summary_hash") or inbound.get("error_type") or ""),
            "created_at": created_at,
            "updated_at": updated_at,
            "created_at_iso": self._iso(created_at),
            "updated_at_iso": self._iso(updated_at),
            "payload": payload,
        }

    def _hydrate_message(self, row: dict[str, Any]) -> dict[str, Any]:
        trace = self._read_private_trace(str(row.get("trace_id") or ""))
        events = trace.get("events") if isinstance(trace.get("events"), dict) else {}
        input_event = self._event(events, "input")
        rag_event = self._event(events, "rag")
        answer_input = self._event(events, "answer_generation_input")
        answer_output = self._event(events, "answer_generation_output")
        final_result = self._event(events, "final_result")
        send_completed = self._event(events, "send_completed")
        trace_data = self._display_trace_data(
            parse_json_object(final_result.get("trace")),
            final_result,
            answer_output,
        )

        rag_chunks = self._rag_chunks(rag_event, trace_data)
        generated_reply = str(
            row.get("generated_reply")
            or send_completed.get("reply_text")
            or final_result.get("reply_text")
            or answer_output.get("answer_text")
            or ""
        )
        send_text = str(row.get("send_text") or send_completed.get("reply_text") or "")
        final_status = str(send_completed.get("final_status") or row.get("final_status") or "unknown")
        pdd_error_code = str(row.get("pdd_error_code") or send_completed.get("pdd_error_code") or "")
        nodes = self._nodes(row, trace_data, final_status, rag_chunks, send_completed)
        timing = self._timing(trace_data, send_completed)
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}

        return {
            **{key: value for key, value in row.items() if key != "payload"},
            "buyer_message": str(row.get("buyer_message") or input_event.get("buyer_message") or ""),
            "generated_reply": generated_reply,
            "send_text": send_text,
            "final_status": final_status,
            "final_status_label": self._status_label(final_status),
            "status_explanation": self._status_explanation(final_status, pdd_error_code),
            "recommended_action": self._recommended_action(final_status, pdd_error_code),
            "rag_query": str(rag_event.get("query") or trace_data.get("rag_query") or ""),
            "rag_chunks": rag_chunks,
            "rag_hit_count": len(rag_chunks),
            "prompt_context": {
                "system_instructions": answer_input.get("system_instructions") or [],
                "conversation_text": answer_input.get("conversation_text") or "",
                "context_blocks": answer_input.get("context_blocks") or [],
                "user_task": answer_input.get("user_task") or "",
                "output_format": answer_input.get("output_format") or "",
                "prompt_hash": answer_input.get("prompt_hash") or trace_data.get("prompt_hash") or "",
            },
            "reply_generation": {
                "intent": final_result.get("intent") or trace_data.get("intent") or "",
                "domain": trace_data.get("domain") or "",
                "action": final_result.get("action") or row.get("reply_action") or "",
                "guardrail_status": final_result.get("guardrail_status") or trace_data.get("guardrail_status") or "",
                "raw_response": answer_output.get("answer_text") or final_result.get("reply_text") or "",
                "llm_provider": trace_data.get("llm_provider") or trace_data.get("answer_generation_source") or "",
                "llm_model": trace_data.get("llm_model") or "",
                "llm_http_status": trace_data.get("llm_http_status") or trace_data.get("answer_http_status"),
                "llm_latency_ms": trace_data.get("llm_latency_ms"),
                "prompt_tokens": trace_data.get("llm_prompt_tokens"),
                "completion_tokens": trace_data.get("llm_completion_tokens"),
                "total_tokens": trace_data.get("llm_total_tokens"),
                "calls_llm": bool(trace_data.get("calls_llm")),
            },
            "send_retry": {
                "send_text": send_text,
                "send_status": final_status,
                "pdd_error_code": pdd_error_code,
                "outbox_id": row.get("outbox_id") or "",
                "retry_count": row.get("retry_count") or 0,
                "max_retries": row.get("max_retries") or 0,
                "next_retry_at": row.get("next_retry_at") or "",
                "last_attempt_at": row.get("last_attempt_at") or "",
                "reply_hash": row.get("reply_hash") or send_completed.get("reply_hash") or "",
                "reply_action": row.get("reply_action") or send_completed.get("reply_action") or "",
                "reply_source": row.get("reply_source") or send_completed.get("reply_source") or "",
            },
            "nodes": nodes,
            "timing": timing,
            "technical": {
                "trace_id": row.get("trace_id") or "",
                "source_message_id": payload.get("source_message_id") or payload.get("msg_id") or "",
                "queue_message_id": payload.get("queue_message_id") or "",
                "inbound_id": row.get("inbound_id") or "",
                "outbox_id": row.get("outbox_id") or "",
                "session_id": row.get("session_id") or "",
                "message_type": row.get("message_type") or "",
                "connects_pgvector": bool(trace_data.get("connects_pgvector")),
                "calls_llm": bool(trace_data.get("calls_llm")),
                "calls_ollama": bool(trace_data.get("calls_ollama")),
                "sends_pdd": final_status not in {"pdd_sending_disabled", "reply_suppressed"},
                "no_send": bool(trace_data.get("no_send")) if "no_send" in trace_data else False,
                "debug_trace_available": bool(events),
            },
            "events": events,
        }

    def _nodes(
        self,
        row: dict[str, Any],
        trace_data: dict[str, Any],
        final_status: str,
        rag_chunks: list[dict[str, Any]],
        send_completed: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            self._node("websocket_received", "WebSocket 收到消息", "passed" if row.get("buyer_message") else "skipped", "买家消息已进入可靠队列。"),
            self._node("inbound_queue", "消息入队", "passed" if row.get("inbound_id") else "skipped", f"入队状态：{row.get('inbound_status') or '未知'}"),
            self._node("dedupe", "去重检查", "passed", "同一 source_message_id 会被队列去重。"),
            self._node("human_lock", "人工锁检查", "passed", "未检测到阻断自动处理的人工锁状态。"),
            self._node(
                "product_context",
                "商品上下文解析",
                self._stage_status(trace_data.get("product_context_status")),
                self._plain(trace_data.get("product_context_status") or "未返回商品上下文状态"),
            ),
            self._node(
                "intent",
                "意图识别",
                self._stage_status(trace_data.get("intent_classifier_status") or trace_data.get("intent")),
                self._plain(trace_data.get("intent") or "未返回意图"),
            ),
            self._node("rag", "RAG 检索", "passed" if rag_chunks else "warning", f"命中 {len(rag_chunks)} 条知识片段。"),
            self._node(
                "prompt",
                "上下文拼接",
                "passed" if trace_data.get("prompt_hash") else "warning",
                "完整上下文见“上下文拼接”页签。",
            ),
            self._node(
                "llm",
                "LLM 生成",
                "passed" if trace_data.get("calls_llm") or trace_data.get("answer_generation_status") == "ok" else "warning",
                self._plain(trace_data.get("answer_generation_status") or "未确认 LLM 状态"),
            ),
            self._node(
                "guardrail",
                "安全拦截",
                self._stage_status(trace_data.get("guardrail_status")),
                self._plain(trace_data.get("guardrail_status") or "未返回安全状态"),
            ),
            self._node(
                "pdd_send",
                "发送 PDD",
                self._send_node_status(final_status),
                self._status_explanation(final_status, str(row.get("pdd_error_code") or send_completed.get("pdd_error_code") or "")),
            ),
            self._node(
                "outbox",
                "Outbox 重试/阻断",
                self._outbox_node_status(final_status),
                f"retry_count={row.get('retry_count') or 0}，状态：{self._status_label(final_status)}",
            ),
        ]

    @staticmethod
    def _node(key: str, label: str, status: str, summary: str) -> dict[str, Any]:
        return {"key": key, "label": label, "status": status, "summary": summary}

    @staticmethod
    def _display_trace_data(
        trace_data: dict[str, Any],
        final_result: dict[str, Any],
        answer_output: dict[str, Any],
    ) -> dict[str, Any]:
        data = dict(trace_data or {})

        intent = str(data.get("intent") or final_result.get("intent") or "").strip()
        if intent:
            data["intent"] = intent
            data.setdefault("intent_classifier_status", "ok")

        action = str(data.get("final_action") or final_result.get("action") or "").strip()
        if action:
            data["final_action"] = action

        guardrail_status = str(data.get("guardrail_status") or final_result.get("guardrail_status") or "").strip()
        if guardrail_status:
            data["guardrail_status"] = guardrail_status

        if not data.get("answer_generation_status"):
            if answer_output.get("answer_text") or final_result.get("reply_text"):
                data["answer_generation_status"] = "ok"
            elif answer_output.get("error_type"):
                data["answer_generation_status"] = "error"

        if "calls_llm" not in data and data.get("answer_generation_status") == "ok":
            data["calls_llm"] = True

        return data

    @staticmethod
    def _rag_chunks(rag_event: dict[str, Any], trace_data: dict[str, Any]) -> list[dict[str, Any]]:
        hits = rag_event.get("hits")
        if isinstance(hits, list) and hits:
            return [hit for hit in hits if isinstance(hit, dict)]
        chunks = trace_data.get("retrieved_chunks")
        if isinstance(chunks, list):
            return [chunk for chunk in chunks if isinstance(chunk, dict)]
        return []

    @staticmethod
    def _timing(trace_data: dict[str, Any], send_completed: dict[str, Any]) -> dict[str, Any]:
        stage = parse_json_object(trace_data.get("stage_timing"))
        if not stage:
            stage = parse_json_object(trace_data.get("latency_breakdown"))
        if send_completed.get("send_ms") is not None:
            stage["send_ms"] = send_completed.get("send_ms")
        if send_completed.get("duration_ms") is not None:
            stage["send_total_ms"] = send_completed.get("duration_ms")
        if trace_data.get("llm_latency_ms") is not None:
            stage["llm_latency_ms"] = trace_data.get("llm_latency_ms")
        return stage

    def _read_private_trace(self, trace_id: str) -> dict[str, Any]:
        if not trace_id:
            return {}
        path = self._debug_trace_dir() / f"{self._safe_trace_id(trace_id)}.json"
        if not path.exists():
            return {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _event(events: Any, key: str) -> dict[str, Any]:
        if isinstance(events, dict) and isinstance(events.get(key), dict):
            return events[key]
        return {}

    @staticmethod
    def _debug_trace_dir() -> Path:
        configured = os.environ.get("AI_WORKFLOW_DEBUG_TRACE_DIR", "")
        root = Path(configured) if configured else Path("temp") / "debug_traces"
        root = root.expanduser()
        return root if root.is_absolute() else Path.cwd() / root

    @staticmethod
    def _safe_trace_id(trace_id: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(trace_id or "missing-trace").strip() or "missing-trace")[:160]

    @staticmethod
    def _iso(value: float) -> str:
        if not value:
            return ""
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()

    @staticmethod
    def _was_send_attempted(status: str) -> bool:
        return status in {
            "sending",
            "sent",
            "reply_send_failed",
            "transfer_send_failed",
            "reply_delivery_unknown",
            "transfer_delivery_unknown",
            "blocked_by_platform_policy",
            "suppressed_duplicate",
            "suppressed_repeated_40013",
            "reply_sent",
        }

    @staticmethod
    def _is_attention_status(status: str) -> bool:
        return status in FINAL_FAILURE_STATUSES

    @staticmethod
    def _stage_status(value: Any) -> str:
        text = str(value or "").lower()
        if text in {"ok", "safe", "hit", "resolved", "reply", "passed"}:
            return "passed"
        if text in {"", "skipped", "disabled", "empty"}:
            return "skipped"
        if "fail" in text or "error" in text or "blocked" in text:
            return "failed"
        return "warning"

    @staticmethod
    def _send_node_status(status: str) -> str:
        if status in SUCCESS_STATUSES:
            return "passed"
        if status in SUPPRESSED_STATUSES:
            return "warning"
        if status in FINAL_FAILURE_STATUSES:
            return "failed"
        return "warning"

    @staticmethod
    def _outbox_node_status(status: str) -> str:
        if status in RETRYABLE_FAILURE_STATUSES:
            return "warning"
        if status in {"blocked_by_platform_policy", "dead_letter"}:
            return "failed"
        if status in {"suppressed_duplicate", "sent", "suppressed_repeated_40013"}:
            return "passed"
        return "skipped"

    @staticmethod
    def _status_label(status: str) -> str:
        labels = {
            "sent": "发送成功",
            "pending_send": "等待发送",
            "sending": "发送中",
            "reply_send_failed": "回复发送失败，等待重试",
            "transfer_send_failed": "转人工话术发送失败，等待重试",
            "reply_delivery_unknown": "回复送达未知，等待确认",
            "transfer_delivery_unknown": "转人工送达未知，等待确认",
            "suppressed_duplicate": "重复内容已压制",
            "suppressed_repeated_40013": "重复 40013 已压制",
            "blocked_by_platform_policy": "PDD 平台策略阻断",
            "pdd_sending_disabled": "PDD 发送开关关闭",
            "dead_letter": "死信，需要人工处理",
            "done": "处理完成",
            "failed": "处理失败",
            "processing": "处理中",
            "pending": "待处理",
        }
        return labels.get(str(status or ""), str(status or "未知"))

    def _status_explanation(self, status: str, pdd_error_code: str = "") -> str:
        if pdd_error_code == "40013":
            return "PDD 文本发送接口拒绝本次消息，这不是 WebSocket 断线；系统会按 outbox 策略重试，连续失败后阻断。"
        if status == "suppressed_duplicate":
            return "同一买家会话短时间内已经发送过相同内容，本次重试被压制，避免重复打扰买家。"
        if status == "blocked_by_platform_policy":
            return "重试后仍被 PDD 拒绝，系统停止自动重试，需要人工查看该会话。"
        if status == "sent":
            return "消息已通过 PDD 发送接口确认成功。"
        if status == "pdd_sending_disabled":
            return "当前 PDD 真实发送开关关闭，系统不会发送真实消息。"
        if status in RETRYABLE_FAILURE_STATUSES:
            return "发送未确认成功，已进入 outbox 重试队列。"
        return self._status_label(status)

    def _recommended_action(self, status: str, pdd_error_code: str = "") -> str:
        if pdd_error_code == "40013" or status == "blocked_by_platform_policy":
            return "请人工进入 PDD 后台查看该买家会话是否允许继续发送，必要时手动回复。"
        if status in RETRYABLE_FAILURE_STATUSES:
            return "等待 outbox 自动重试；若长时间未恢复，请检查授权状态和 PDD 发送接口。"
        if status == "suppressed_duplicate":
            return "无需处理；系统为避免重复回复已压制本次发送。"
        return "无需处理。"

    @staticmethod
    def _plain(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _table_warning(self) -> str | None:
        count, warning = self.db.count("SELECT COUNT(*) FROM pdd_inbound_message_queue", required_tables=("pdd_inbound_message_queue",))
        if warning:
            return warning
        return None if count >= 0 else "unknown"
