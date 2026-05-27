from pydantic import BaseModel


class SopRecord(BaseModel):
    id: str
    shop_id: str
    domain: str
    title: str
    version: str
    status: str
    indexed: bool
    updated_at: str


class SopDetail(SopRecord):
    content: str
    published_at: str | None = None


class SopCreate(BaseModel):
    shop_id: str
    domain: str
    title: str
    content: str
    version: str = "draft"
    status: str = "draft"


class SopUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    version: str | None = None
    status: str | None = None
