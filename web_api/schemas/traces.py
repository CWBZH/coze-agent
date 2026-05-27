from pydantic import BaseModel


class TraceSummary(BaseModel):
    time: str
    trace_id: str
    shop_id: str
    buyer_id: str
    session_id: str
    intent: str
    domain: str | None
    action: str
    rag_hit_count: int
    guardrail_status: str
    answer_status: str
    final_status: str
    latency_ms: int
    no_send: bool
