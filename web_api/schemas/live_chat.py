from typing import Any

from pydantic import BaseModel, Field


class LiveChatSessionCreate(BaseModel):
    shop_id: str
    buyer_id: str | None = None


class LiveChatSession(BaseModel):
    session_id: str
    no_send: bool = True
    engine: str = "internal"
    shop_id: str | None = None
    buyer_id: str | None = None


class LiveChatMessageRequest(BaseModel):
    shop_id: str
    buyer_id: str | None = None
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    use_rag: bool = True
    use_llm_intent_classifier: bool = True
    use_llm_answer_generator: bool = True
    use_real_engine: bool = False
    use_real_llm: bool = False
    use_real_ollama: bool = False
    use_real_pgvector: bool = False
    use_real_intent_classifier: bool = False
    use_real_answer_generator: bool = False
    product_version: str = "real-product-v1"
    sop_version: str = "sop-test-v1"
    rag_top_k: int = 3
    smoke_profile: str | None = None
    no_send: bool = True


class LiveChatMessageResponse(BaseModel):
    reply: str
    action: str
    intent: str
    domain: str | None
    session_id: str
    no_send: bool = True
    trace: dict
