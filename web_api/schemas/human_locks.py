from pydantic import BaseModel, Field


class HumanLockItem(BaseModel):
    id: str
    shop_id: str
    buyer_id: str
    session_id: str
    status: str
    reason: str = ""
    intent: str = ""
    source: str = "unknown"
    trace_id: str = ""
    last_message_preview: str = ""
    locked_at: str = ""
    updated_at: str = ""
    can_unlock: bool = True


class HumanLockListResponse(BaseModel):
    items: list[HumanLockItem]
    total: int
    shop_id: str
    warning: str | None = None


class HumanLockUnlockRequest(BaseModel):
    shop_id: str | None = None
    operator: str = "local_admin"
    reason: str = "manual_unlock_after_review"


class HumanLockUnlockResponse(BaseModel):
    id: str
    shop_id: str
    unlocked: bool
    already_unlocked: bool
    operator: str
    reason: str
    updated_at: str


class HumanLockUnlockBySessionRequest(BaseModel):
    shop_id: str | None = None
    buyer_id: str | None = None
    session_id: str | None = None
    operator: str = "local_admin"
    reason: str = "manual_unlock_after_review"


class HumanLockBulkUnlockRequest(BaseModel):
    shop_id: str | None = None
    operator: str = "local_admin"
    reason: str = "bulk_unlock_after_deploy"
    limit: int = Field(default=100, ge=1, le=500)


class HumanLockBatchUnlockResponse(BaseModel):
    shop_id: str
    matched_count: int
    unlocked_count: int
    operator: str
    reason: str
