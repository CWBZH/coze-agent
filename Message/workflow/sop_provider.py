"""Read-only SOP provider for internal workflow policy lookups.

The provider wraps the Markdown SOP loader and exposes a small query surface for
shop/domain lookups. It never writes to DB and never synchronizes FastGPT.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .sop_loader import SUPPORTED_DOMAINS, SopLoadError, SopRecord, load_sop_markdown


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SopProviderErrorSummary:
    """Sanitized, non-fatal provider error summary."""

    source: str
    section: str
    field: str
    message: str


@dataclass
class SOPProvider:
    """Lightweight read-only SOP record provider."""

    records: list[SopRecord] = field(default_factory=list)
    errors: list[SopProviderErrorSummary] = field(default_factory=list)

    @classmethod
    def from_markdown_file(cls, path: str | Path) -> "SOPProvider":
        """Create a provider from one Markdown SOP file."""
        return cls.from_markdown_files([path])

    @classmethod
    def from_markdown_files(cls, paths: Iterable[str | Path]) -> "SOPProvider":
        """Create a provider from Markdown SOP files.

        File and parse errors are captured in ``errors`` and logged as sanitized
        summaries so callers can keep the main workflow moving.
        """
        records: list[SopRecord] = []
        errors: list[SopProviderErrorSummary] = []

        for path in paths:
            source = str(Path(path))
            try:
                result = load_sop_markdown(path)
            except Exception as exc:  # pragma: no cover - defensive boundary for workflow callers
                summary = SopProviderErrorSummary(
                    source=source,
                    section="",
                    field="loader",
                    message=f"failed to load SOP markdown: {type(exc).__name__}",
                )
                errors.append(summary)
                _log_error_summary(summary)
                continue

            records.extend(result.records)
            for load_error in result.errors:
                summary = _summarize_load_error(load_error)
                errors.append(summary)
                _log_error_summary(summary)

        return cls(records=records, errors=errors)

    def get_records(self, shop_id: str, domain: str) -> list[SopRecord]:
        """Return records matching ``shop_id`` and ``domain``.

        Missing or unsupported domains and no-match results return an empty list
        with a sanitized error summary instead of raising.
        """
        normalized_shop_id = _clean(shop_id)
        normalized_domain = _clean(domain)
        if not normalized_domain:
            self._record_query_error(
                source="query",
                field="domain",
                message="missing domain",
                shop_id=normalized_shop_id,
                domain=normalized_domain,
            )
            return []

        if normalized_domain not in SUPPORTED_DOMAINS:
            self._record_query_error(
                source="query",
                field="domain",
                message="unsupported domain",
                shop_id=normalized_shop_id,
                domain=normalized_domain,
            )
            return []

        matches = [
            record
            for record in self.records
            if record.domain == normalized_domain and record.shop_id == normalized_shop_id
        ]
        if not matches:
            self._record_query_error(
                source="query",
                field="domain",
                message="no SOP records for shop/domain",
                shop_id=normalized_shop_id,
                domain=normalized_domain,
            )
        return matches

    def get_error_summary(self) -> list[SopProviderErrorSummary]:
        """Return a copy of sanitized provider errors."""
        return list(self.errors)

    def _record_query_error(self, *, source: str, field: str, message: str, shop_id: str, domain: str) -> None:
        summary = SopProviderErrorSummary(source=source, section="", field=field, message=message)
        self.errors.append(summary)
        logger.warning(
            "SOP provider query error: source=%s field=%s message=%s shop_id=%s domain=%s",
            summary.source,
            summary.field,
            summary.message,
            shop_id,
            domain,
        )


def _summarize_load_error(error: SopLoadError) -> SopProviderErrorSummary:
    return SopProviderErrorSummary(
        source=error.source,
        section=error.section,
        field=error.field,
        message=error.message,
    )


def _log_error_summary(summary: SopProviderErrorSummary) -> None:
    logger.warning(
        "SOP provider load error: source=%s section=%s field=%s message=%s",
        summary.source,
        summary.section,
        summary.field,
        summary.message,
    )


def _clean(value: object) -> str:
    return str(value or "").strip()
