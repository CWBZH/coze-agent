from datetime import datetime
from uuid import uuid4

from web_api.schemas.sop import SopCreate, SopDetail, SopRecord, SopUpdate


class SopService:
    def __init__(self) -> None:
        self._records = [
            SopDetail(
                id="sop-logistics",
                shop_id="323473738",
                domain="logistics_policy",
                title="物流订单查询 SOP",
                content="用户咨询发货、到货、快递、物流状态时，引导查看订单物流页；不能编造具体物流状态，可说明如需核实会转人工确认。",
                version="sop-test-v1",
                status="published",
                indexed=True,
                updated_at="2026-05-25 18:00",
                published_at="2026-05-25 18:00",
            ),
            SopDetail(
                id="sop-after-sales",
                shop_id="323473738",
                domain="after_sales_evidence",
                title="售后取证处理 SOP",
                content="用户反馈破损、漏液、少发、错发、质量问题时，先收集商品照片、外包装照片、订单信息和问题描述；不承诺退款、赔偿、补发结果。",
                version="sop-test-v1",
                status="published",
                indexed=True,
                updated_at="2026-05-25 18:00",
                published_at="2026-05-25 18:00",
            ),
        ]

    def list_records(self, shop_id: str | None = None, domain: str | None = None, status: str | None = None) -> list[SopRecord]:
        records: list[SopDetail] = self._records
        if shop_id:
            records = [item for item in records if item.shop_id == shop_id]
        if domain:
            records = [item for item in records if item.domain == domain]
        if status:
            records = [item for item in records if item.status == status]
        return [SopRecord(**item.model_dump(exclude={"content", "published_at"})) for item in records]

    def get_record(self, record_id: str) -> SopDetail:
        return self._find(record_id)

    def create_record(self, payload: SopCreate) -> SopDetail:
        record = SopDetail(
            id=f"sop-{uuid4().hex[:8]}",
            shop_id=payload.shop_id,
            domain=payload.domain,
            title=payload.title,
            content=payload.content,
            version=payload.version,
            status=payload.status,
            indexed=False,
            updated_at=datetime.utcnow().isoformat(timespec="seconds"),
            published_at=None,
        )
        self._records.append(record)
        return record

    def update_record(self, record_id: str, payload: SopUpdate) -> SopDetail:
        record = self._find(record_id)
        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(record, key, value)
        record.updated_at = datetime.utcnow().isoformat(timespec="seconds")
        return record

    def publish(self, record_id: str) -> SopDetail:
        record = self._find(record_id)
        record.status = "published"
        record.published_at = datetime.utcnow().isoformat(timespec="seconds")
        record.updated_at = record.published_at
        return record

    def _find(self, record_id: str) -> SopDetail:
        for record in self._records:
            if record.id == record_id:
                return record
        raise KeyError(record_id)
