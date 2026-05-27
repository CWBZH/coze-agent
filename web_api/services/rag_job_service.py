from datetime import datetime
from uuid import uuid4

from web_api.schemas.rag import RagJob, RagJobCreate


class RagJobService:
    def __init__(self) -> None:
        self._jobs = [
            RagJob(
                job_id="rag-job-demo",
                shop_id="323473738",
                source_type="product",
                domain="product_catalog",
                version="real-product-v1",
                status="completed_mock",
                chunk_count=82,
                embedded_count=0,
                indexed_count=0,
                error_summary=None,
                created_at="2026-05-25 18:00",
                finished_at="2026-05-25 18:01",
                dry_run=True,
            )
        ]

    def list_jobs(self) -> list[RagJob]:
        return self._jobs

    def create_job(self, payload: RagJobCreate) -> RagJob:
        job = RagJob(
            job_id=f"rag-job-{uuid4().hex[:8]}",
            shop_id=payload.shop_id,
            source_type=payload.source_type,
            domain=payload.domain,
            version=payload.version,
            status="queued_dry_run",
            chunk_count=0,
            embedded_count=0,
            indexed_count=0,
            error_summary=None,
            created_at=datetime.utcnow().isoformat(timespec="seconds"),
            dry_run=True,
            calls_ollama=False,
            connects_pgvector=False,
        )
        self._jobs.insert(0, job)
        return job
