"""Ingestion payloads."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.schemas.common import ORMModel


class UrlIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    urls: list[HttpUrl] = Field(min_length=1, max_length=200)
    vendor_hint: str | None = Field(
        default=None, description="Vendor the submitter believes these pages are about"
    )
    vendor_id: uuid.UUID | None = None
    auto_extract: bool = Field(
        default=True, description="Queue AI extraction as soon as each page is parsed"
    )
    auto_promote: bool = Field(
        default=False,
        description="Write high-confidence extractions without human review",
    )
    follow_document_links: bool = Field(
        default=False, description="Also fetch PDF/XLSX links found on each page"
    )
    batch_name: str | None = None


class WebSearchIngestRequest(BaseModel):
    """Discovery through Parallel AI, then ingestion of what it finds."""

    model_config = ConfigDict(extra="forbid")

    objective: str | None = Field(
        default=None, max_length=1000, description="Research goal; a recipe is used if omitted"
    )
    recipe: str | None = Field(
        default=None,
        description="vendor_discovery | vendor_intelligence | pump_model",
    )
    pump_type: str | None = None
    vendor_name: str | None = None
    model_code: str | None = None
    country: str | None = Field(default=None, max_length=2)
    queries: list[str] = Field(default_factory=list, max_length=5)
    max_results: int = Field(default=10, ge=1, le=50)
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    fetch_full_pages: bool = Field(
        default=True,
        description=(
            "Fetch each result URL rather than relying on the search excerpt. Excerpts "
            "are often only 100-200 characters, which is not enough to extract a "
            "specification from, so leave this on for anything but a smoke test."
        ),
    )
    auto_extract: bool = True
    auto_promote: bool = Field(
        default=False,
        description=(
            "Write high-confidence extractions straight into the system of record "
            "instead of queueing them for human review. This is how vendor data gets "
            "captured from the web unattended. Everything promoted still carries full "
            "provenance and is flagged by the data-quality validators."
        ),
    )
    min_confidence_to_promote: float = Field(
        default=0.85,
        ge=0.5,
        le=1.0,
        description=(
            "Overall extraction confidence required before auto-promotion. Lower it to "
            "capture more and review more; raise it to capture less and trust it more."
        ),
    )

    @field_validator("country")
    @classmethod
    def _upper(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class ManualSubmissionRequest(BaseModel):
    """The manual-entry form. Recorded as a source so it stays as traceable as a crawl."""

    model_config = ConfigDict(extra="forbid")

    vendor_name: str = Field(min_length=2, max_length=255)
    vendor_country: str | None = Field(default=None, max_length=2)
    pump_name: str | None = None
    model_code: str | None = None
    pump_type: str | None = None
    applicable_standard: str | None = None
    service_application: str | None = None
    submitted_by_organisation: str | None = None
    confidence_level: str = Field(
        default="vendor_declared",
        description="verified | vendor_declared | third_party | estimated",
    )
    technical: dict[str, Any] = Field(default_factory=dict)
    commercial: dict[str, Any] = Field(default_factory=dict)
    dimensional: dict[str, Any] = Field(default_factory=dict)
    delivery: dict[str, Any] = Field(default_factory=dict)
    operational: dict[str, Any] = Field(default_factory=dict)
    administrative: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class CrawlScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=255)
    target_type: str = Field(description="url | sitemap | vendor_site | parallel_query")
    target: str = Field(min_length=3, max_length=2000)
    vendor_id: uuid.UUID | None = None
    cron_expression: str = Field(default="0 3 * * 1")
    max_depth: int = Field(default=1, ge=0, le=4)
    max_pages: int = Field(default=50, ge=1, le=1000)
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    auto_extract: bool = True
    is_active: bool = True


class SourceOut(ORMModel):
    id: uuid.UUID
    source_type: str
    status: str
    title: str | None = None
    source_url: str | None = None
    publisher: str | None = None
    captured_at: Any = None
    content_type: str | None = None
    content_hash: str | None = None
    parsed_text_chars: int | None = None
    confidence_level: str
    reliability_score: float | None = None
    is_authoritative: bool
    vendor_hint: str | None = None
    error_message: str | None = None
    import_batch_id: uuid.UUID | None = None


class SourceDetail(SourceOut):
    parsed_text: str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    extracted_entity_count: int = 0
    documents: list[dict[str, Any]] = Field(default_factory=list)


class ImportBatchOut(ORMModel):
    id: uuid.UUID
    name: str
    import_mode: str
    source_type: str
    status: str
    total_items: int
    processed_items: int
    failed_items: int
    promoted_items: int
    needs_review_items: int
    auto_promote: bool
    progress_pct: float = 0.0
    started_at: Any = None
    finished_at: Any = None
    error_summary: str | None = None
    created_at: Any = None


class DocumentOut(ORMModel):
    id: uuid.UUID
    filename: str
    document_kind: str
    mime_type: str | None = None
    size_bytes: int | None = None
    page_count: int | None = None
    checksum_sha256: str | None = None
    vendor_id: uuid.UUID | None = None
    pump_model_id: uuid.UUID | None = None
    revision: str | None = None
    created_at: Any = None
    download_url: str | None = None
