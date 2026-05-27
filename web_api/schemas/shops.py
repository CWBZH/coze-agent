from pydantic import BaseModel


class ShopSummary(BaseModel):
    shop_id: str
    shop_name: str
    channel: str
    internal_enabled: bool
    rag_enabled: bool
    llm_enabled: bool
    intent_classifier_enabled: bool
    answer_generator_enabled: bool
    account_status: str
    websocket_status: str
    no_send: bool
    shadow_enabled: bool
    last_activity: str | None = None


class ShopDetail(BaseModel):
    shop_id: str
    shop_name: str
    channel: str
    internal_engine_summary: dict
    product_knowledge_count: int
    sop_coverage: dict
    rag_index_status: dict
    recent_trace_summary: dict
    warning: str | None = None
