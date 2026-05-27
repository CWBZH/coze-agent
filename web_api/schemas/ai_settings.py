from pydantic import BaseModel


class SecretStatus(BaseModel):
    llm_provider: str = "configured"
    ollama: str = "configured"
    pgvector: str = "configured"
    pdd_sending: str = "disabled"


class AiSettings(BaseModel):
    shop_id: str
    internal_enabled: bool = True
    shadow_enabled: bool = False
    send_enabled: bool = False
    no_send_mode: bool = True
    rag_enabled: bool = True
    llm_enabled: bool = True
    intent_classifier_enabled: bool = True
    answer_generator_enabled: bool = True
    guardrail_enabled: bool = True
    product_version: str = "real-product-v1"
    sop_version: str = "sop-test-v1"
    rag_top_k: int = 3
    similarity_threshold: float = 0.75
    guardrail_strictness: str = "high"
    secret_status: SecretStatus = SecretStatus()
    warning: str | None = None


class AiSettingsUpdate(BaseModel):
    internal_enabled: bool | None = None
    shadow_enabled: bool | None = None
    send_enabled: bool | None = None
    rag_enabled: bool | None = None
    llm_enabled: bool | None = None
    intent_classifier_enabled: bool | None = None
    answer_generator_enabled: bool | None = None
    guardrail_enabled: bool | None = None
    product_version: str | None = None
    sop_version: str | None = None
    rag_top_k: int | None = None
    similarity_threshold: float | None = None
    guardrail_strictness: str | None = None
