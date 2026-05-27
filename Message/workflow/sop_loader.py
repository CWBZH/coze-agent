"""Markdown SOP loader for internal workflow knowledge.

This module is intentionally read-only and self-contained. It parses local
Markdown files into deterministic records and never writes to DB, FastGPT, or
other workflow engines.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


SUPPORTED_DOMAINS = frozenset(
    {
        "logistics_policy",
        "after_sales_evidence",
        "promotion_policy",
        "redline_escalation",
        "sensitive_user_safety",
    }
)

REQUIRED_FIELDS = (
    "kb_item_id",
    "domain",
    "title",
    "intent_examples",
    "approved_answer",
    "forbidden_phrases",
    "should_transfer_human",
    "risk_level",
    "version",
)

LIST_FIELDS = frozenset({"intent_examples", "forbidden_phrases"})
BOOLEAN_FIELDS = frozenset({"should_transfer_human"})
TEXT_FIELDS = frozenset(
    {
        "kb_item_id",
        "domain",
        "title",
        "approved_answer",
        "risk_level",
        "version",
        "content_hash",
    }
)
KNOWN_FIELDS = frozenset(REQUIRED_FIELDS) | frozenset({"content_hash"})


@dataclass(frozen=True)
class SopLoadError:
    """Non-fatal parse or validation error."""

    source: str
    section: str
    field: str
    message: str


@dataclass(frozen=True)
class SopRecord:
    """Structured SOP item parsed from Markdown."""

    kb_item_id: str
    domain: str
    title: str
    intent_examples: list[str]
    approved_answer: str
    forbidden_phrases: list[str]
    should_transfer_human: bool
    risk_level: str
    version: str
    content_hash: str
    shop_id: str = ""
    source: str = ""


@dataclass(frozen=True)
class SopLoadResult:
    """Loader result. Parse failures are reported here instead of raised."""

    records: list[SopRecord] = field(default_factory=list)
    errors: list[SopLoadError] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


def load_sop_markdown(
    path: str | Path,
    *,
    domains: Iterable[str] | None = None,
    shop_id: str | None = None,
    version: str | None = None,
) -> SopLoadResult:
    """Read and parse a Markdown SOP file.

    File read errors are returned in ``errors`` so callers can continue loading
    other files.
    """
    source_path = Path(path)
    try:
        text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        return SopLoadResult(
            errors=[
                SopLoadError(
                    source=str(source_path),
                    section="",
                    field="file",
                    message=f"failed to read markdown file: {type(exc).__name__}",
                )
            ]
        )

    return parse_sop_markdown(
        text,
        source=str(source_path),
        domains=domains,
        shop_id=shop_id,
        version=version,
    )


def parse_sop_markdown(
    text: str,
    *,
    source: str = "<memory>",
    domains: Iterable[str] | None = None,
    shop_id: str | None = None,
    version: str | None = None,
) -> SopLoadResult:
    """Parse Markdown text into SOP records and non-fatal errors."""
    allowed_domains, domain_errors = _normalize_domain_filter(domains, source)
    metadata, body = _split_front_matter(text or "")
    errors: list[SopLoadError] = list(domain_errors)

    effective_shop_id = _clean_scalar(shop_id if shop_id is not None else metadata.get("shop_id", ""))
    effective_version = _clean_scalar(version if version is not None else metadata.get("version", ""))
    normalized_metadata = {
        key: value
        for key, value in {
            "shop_id": effective_shop_id,
            "version": effective_version,
        }.items()
        if value
    }

    records: list[SopRecord] = []
    for section in _split_sections(body):
        raw_record, section_errors = _parse_section(section, source)
        errors.extend(section_errors)
        if not raw_record:
            continue

        if effective_version and not _clean_scalar(raw_record.get("version", "")):
            raw_record["version"] = effective_version

        record_errors = _validate_record(raw_record, section.title, source)
        if record_errors:
            errors.extend(record_errors)
            continue

        domain = str(raw_record["domain"])
        if allowed_domains is not None and domain not in allowed_domains:
            continue

        records.append(_build_record(raw_record, section.title, source, effective_shop_id))

    return SopLoadResult(records=records, errors=errors, metadata=normalized_metadata)


@dataclass(frozen=True)
class _Section:
    title: str
    lines: list[str]


def _split_front_matter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    metadata: dict[str, str] = {}
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = _clean_scalar(value)

    if end_index is None:
        return {}, text
    return metadata, "\n".join(lines[end_index + 1 :])


def _split_sections(text: str) -> list[_Section]:
    sections: list[_Section] = []
    current_title = ""
    current_lines: list[str] = []

    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            if current_title or any(part.strip() for part in current_lines):
                sections.append(_Section(title=current_title, lines=current_lines))
            current_title = stripped[3:].strip()
            current_lines = []
            continue
        current_lines.append(line)

    if current_title or any(part.strip() for part in current_lines):
        sections.append(_Section(title=current_title, lines=current_lines))
    return sections


def _parse_section(section: _Section, source: str) -> tuple[dict[str, object], list[SopLoadError]]:
    values: dict[str, object] = {}
    errors: list[SopLoadError] = []
    current_field = ""
    current_mode = ""
    block_lines: list[str] = []

    def flush_block() -> None:
        nonlocal block_lines, current_field, current_mode
        if current_field and current_mode == "block":
            values[current_field] = "\n".join(block_lines).strip()
        block_lines = []
        current_mode = ""

    for line in section.lines:
        stripped = line.strip()
        if not stripped:
            if current_mode == "block":
                block_lines.append("")
            continue

        key, separator, value = stripped.partition(":")
        if separator and key.strip() in KNOWN_FIELDS:
            flush_block()
            current_field = key.strip()
            if current_field in LIST_FIELDS:
                values[current_field] = []
                current_mode = "list"
                inline_value = _clean_scalar(value)
                if inline_value:
                    values[current_field] = _parse_inline_list(inline_value)
            elif value.strip() == "|":
                current_mode = "block"
                block_lines = []
            else:
                values[current_field] = _clean_scalar(value)
                current_mode = "scalar"
            continue

        if current_mode == "list" and current_field in LIST_FIELDS:
            item = _parse_list_item(stripped)
            if item:
                values.setdefault(current_field, [])
                cast_list = values[current_field]
                if isinstance(cast_list, list):
                    cast_list.append(item)
            else:
                errors.append(
                    SopLoadError(source=source, section=section.title, field=current_field, message="invalid list item")
                )
            continue

        if current_mode == "block":
            block_lines.append(line.strip())
            continue

        if stripped.startswith("#"):
            continue

        errors.append(SopLoadError(source=source, section=section.title, field="", message="unrecognized line"))

    flush_block()
    return values, errors


def _validate_record(raw_record: dict[str, object], section: str, source: str) -> list[SopLoadError]:
    errors: list[SopLoadError] = []
    for field_name in REQUIRED_FIELDS:
        value = raw_record.get(field_name)
        if field_name in LIST_FIELDS:
            if not isinstance(value, list) or not [item for item in value if _clean_scalar(item)]:
                errors.append(SopLoadError(source=source, section=section, field=field_name, message="missing required field"))
        elif not _clean_scalar(value):
            errors.append(SopLoadError(source=source, section=section, field=field_name, message="missing required field"))

    domain = _clean_scalar(raw_record.get("domain", ""))
    if domain and domain not in SUPPORTED_DOMAINS:
        errors.append(SopLoadError(source=source, section=section, field="domain", message="unsupported domain"))

    raw_transfer = _clean_scalar(raw_record.get("should_transfer_human", ""))
    if raw_transfer and _parse_bool(raw_transfer) is None:
        errors.append(SopLoadError(source=source, section=section, field="should_transfer_human", message="invalid boolean"))

    return errors


def _build_record(raw_record: dict[str, object], section: str, source: str, shop_id: str) -> SopRecord:
    del section
    payload = {
        "kb_item_id": _clean_scalar(raw_record["kb_item_id"]),
        "domain": _clean_scalar(raw_record["domain"]),
        "title": _clean_scalar(raw_record["title"]),
        "intent_examples": _clean_list(raw_record["intent_examples"]),
        "approved_answer": _clean_scalar(raw_record["approved_answer"]),
        "forbidden_phrases": _clean_list(raw_record["forbidden_phrases"]),
        "should_transfer_human": bool(_parse_bool(_clean_scalar(raw_record["should_transfer_human"]))),
        "risk_level": _clean_scalar(raw_record["risk_level"]),
        "version": _clean_scalar(raw_record["version"]),
        "shop_id": _clean_scalar(shop_id),
    }
    payload["content_hash"] = _content_hash(payload)
    return SopRecord(source=source, **payload)


def _normalize_domain_filter(domains: Iterable[str] | None, source: str) -> tuple[set[str] | None, list[SopLoadError]]:
    if domains is None:
        return None, []

    normalized = {_clean_scalar(domain) for domain in domains if _clean_scalar(domain)}
    errors = [
        SopLoadError(source=source, section="", field="domain", message=f"unsupported domain filter: {domain}")
        for domain in sorted(normalized - SUPPORTED_DOMAINS)
    ]
    return normalized & SUPPORTED_DOMAINS, errors


def _content_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _clean_scalar(value: object) -> str:
    return str(value or "").strip().strip('"').strip("'").strip()


def _clean_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_scalar(item) for item in value if _clean_scalar(item)]


def _parse_inline_list(value: str) -> list[str]:
    stripped = value.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return [_clean_scalar(item) for item in stripped[1:-1].split(",") if _clean_scalar(item)]
    return [_clean_scalar(stripped)] if stripped else []


def _parse_list_item(value: str) -> str:
    if value.startswith("- "):
        return _clean_scalar(value[2:])
    return ""


def _parse_bool(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "1", "y"}:
        return True
    if normalized in {"false", "no", "0", "n"}:
        return False
    return None
