from datetime import datetime
from uuid import uuid4

from web_api.schemas.traces import TraceSummary


def _demo_chunks() -> list[dict]:
    return [
        {
            "chunk_id": "chunk-product-943269377110-1",
            "domain": "product_catalog",
            "content": "这款身体素颜霜主打提亮肤色、防水防汗，价格以商品页面和结算页为准。",
            "score": 0.92,
            "metadata": {"goods_id": "943269377110", "source_type": "product"},
        }
    ]


class TraceService:
    def __init__(self) -> None:
        self._details: dict[str, dict] = {}
        trace_id = "trace-demo-1"
        self._details[trace_id] = self._build_detail(
            trace_id=trace_id,
            shop_id="323473738",
            buyer_id="buyer-demo",
            session_id="session-demo",
            buyer_message="这个多少钱",
            ai_reply="亲亲，这款价格以商品页面和结算页显示为准，现在可以看下页面活动价哦。",
            intent="product_basic",
            domain="product_catalog",
            action="reply",
        )

    def list_traces(self) -> list[TraceSummary]:
        return [
            TraceSummary(
                time=detail["time"],
                trace_id=detail["trace_id"],
                shop_id=detail["shop_id"],
                buyer_id=detail["buyer_id"],
                session_id=detail["session_id"],
                intent=detail["intent"],
                domain=detail["domain"],
                action=detail["action"],
                rag_hit_count=len(detail["retrieved_chunks"]),
                guardrail_status=detail["guardrail_status"],
                answer_status=detail["answer_status"],
                final_status=detail["final_status"],
                latency_ms=sum(detail["latency_breakdown"].values()),
                no_send=detail["no_send"],
            )
            for detail in self._details.values()
        ]

    def get_trace(self, trace_id: str) -> dict:
        return self._details.get(trace_id) or next(iter(self._details.values()))

    def add_trace(self, shop_id: str, buyer_id: str, session_id: str, buyer_message: str, ai_reply: str, intent: str, domain: str | None, action: str) -> dict:
        trace_id = f"trace-{uuid4().hex[:8]}"
        detail = self._build_detail(trace_id, shop_id, buyer_id, session_id, buyer_message, ai_reply, intent, domain, action)
        self._details[trace_id] = detail
        return detail

    def _build_detail(
        self,
        trace_id: str,
        shop_id: str,
        buyer_id: str,
        session_id: str,
        buyer_message: str,
        ai_reply: str,
        intent: str,
        domain: str | None,
        action: str,
    ) -> dict:
        chunks = _demo_chunks() if domain == "product_catalog" else []
        return {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "trace_id": trace_id,
            "shop_id": shop_id,
            "buyer_id": buyer_id,
            "session_id": session_id,
            "buyer_message": buyer_message,
            "ai_reply": ai_reply,
            "prompt": f"你是拼多多店铺客服，只回答当前消息：{buyer_message}",
            "raw_response": ai_reply,
            "retrieved_chunks": chunks,
            "rag_query": f"当前消息: {buyer_message}",
            "product_context": {"goods_id": "943269377110", "goods_name": "脖子身体懒人素颜霜"} if domain == "product_catalog" else {},
            "intent": intent,
            "domain": domain,
            "action": action,
            "guardrail_status": "safe",
            "answer_status": "mock",
            "final_status": "no_send",
            "latency_breakdown": {
                "context_build": 8,
                "classifier": 12,
                "rag": 14 if chunks else 0,
                "llm": 0,
                "guardrail": 4,
            },
            "errors": [],
            "no_send": True,
            "sends_pdd": False,
        }
