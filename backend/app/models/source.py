"""Sources, documents and import batches - the raw layer of the pipeline."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDelete, TenantScoped, Timestamps, UUIDPrimaryKey
from app.models.enums import (
    ConfidenceLevel,
    DocumentKind,
    IngestionStatus,
    SourceType,
)
from app.models.types import Json, Ratio, pg_enum

if TYPE_CHECKING:
    from app.models.ai import ExtractedEntity


class Source(UUIDPrimaryKey, Timestamps, SoftDelete, TenantScoped, Base):
    """One captured piece of evidence.

    Every intelligence value in the platform can be walked back to a row here, which
    keeps the AI layer auditable: raw content in, parsed text beside it, extraction
    output linked by ``extracted_entities``.
    """

    __tablename__ = "sources"
    __table_args__ = (
        Index("ix_sources_tenant_status", "tenant_id", "status"),
        Index("ix_sources_type_captured", "source_type", "captured_at"),
        Index("ix_sources_content_hash", "content_hash"),
        Index("ix_sources_url", "source_url"),
    )

    source_type: Mapped[SourceType] = mapped_column(
        pg_enum(SourceType, "source_type"), nullable=False
    )
    status: Mapped[IngestionStatus] = mapped_column(
        pg_enum(IngestionStatus, "ingestion_status"), nullable=False, default=IngestionStatus.QUEUED
    )
    title: Mapped[str | None] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(String(2000))
    canonical_url: Mapped[str | None] = mapped_column(String(2000))
    publisher: Mapped[str | None] = mapped_column(String(255))
    author: Mapped[str | None] = mapped_column(String(255))
    language: Mapped[str | None] = mapped_column(String(8))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="When PumpAtlas fetched the source"
    )
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(160))
    content_hash: Mapped[str | None] = mapped_column(
        String(64), comment="SHA-256 of raw bytes; drives re-crawl dedupe"
    )
    raw_content: Mapped[str | None] = mapped_column(
        Text, comment="Raw HTML / JSON payload as captured; large binaries live in documents"
    )
    parsed_text: Mapped[str | None] = mapped_column(Text, comment="Plain text used for extraction")
    parsed_text_chars: Mapped[int | None] = mapped_column(Integer)
    source_metadata: Mapped[dict] = mapped_column(
        Json, nullable=False, default=dict, comment="Headers, robots directives, crawl context"
    )
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(
        pg_enum(ConfidenceLevel, "confidence_level"),
        nullable=False,
        default=ConfidenceLevel.UNKNOWN,
    )
    reliability_score: Mapped[float | None] = mapped_column(
        Ratio, comment="0-1 trust in the publisher; OEM site > distributor > forum"
    )
    is_authoritative: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="True for OEM/official documents"
    )
    parallel_search_id: Mapped[str | None] = mapped_column(
        String(120), comment="Parallel AI run that surfaced this result"
    )
    parallel_result_rank: Mapped[int | None] = mapped_column(Integer)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="SET NULL"), index=True
    )
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    vendor_hint: Mapped[str | None] = mapped_column(
        String(255), comment="Vendor the submitter believes this source is about"
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    documents: Mapped[list[Document]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )
    extracted_entities: Mapped[list[ExtractedEntity]] = relationship(back_populates="source")

    def __repr__(self) -> str:
        return f"<Source {self.source_type} {self.title or self.source_url}>"


class Document(UUIDPrimaryKey, Timestamps, SoftDelete, TenantScoped, Base):
    """A binary artefact in object storage (datasheet, curve, quotation, certificate)."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_tenant_kind", "tenant_id", "document_kind"),
        Index("ix_documents_vendor", "vendor_id"),
        Index("ix_documents_pump_model", "pump_model_id"),
        UniqueConstraint("tenant_id", "storage_key"),
    )

    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vendors.id", ondelete="SET NULL")
    )
    pump_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pumps.id", ondelete="SET NULL")
    )
    pump_model_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pump_models.id", ondelete="SET NULL")
    )
    document_kind: Mapped[DocumentKind] = mapped_column(
        pg_enum(DocumentKind, "document_kind"), nullable=False, default=DocumentKind.OTHER
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_key: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="S3 object key (or local path in dev)"
    )
    storage_bucket: Mapped[str | None] = mapped_column(String(160))
    mime_type: Mapped[str | None] = mapped_column(String(160))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    ocr_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    document_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[str | None] = mapped_column(String(40))
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    doc_metadata: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)

    source: Mapped[Source | None] = relationship(back_populates="documents")


class ImportBatch(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """A single ingestion run - drives the Import Queue screen."""

    __tablename__ = "import_batches"
    __table_args__ = (Index("ix_import_batches_tenant_status", "tenant_id", "status"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    import_mode: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        comment="file_upload | url_list | scheduled_crawl | api_sync | web_search | manual_form",
    )
    source_type: Mapped[SourceType] = mapped_column(
        pg_enum(SourceType, "source_type"), nullable=False
    )
    status: Mapped[IngestionStatus] = mapped_column(
        pg_enum(IngestionStatus, "ingestion_status"), nullable=False, default=IngestionStatus.QUEUED
    )
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    promoted_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    needs_review_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    config: Mapped[dict] = mapped_column(
        Json, nullable=False, default=dict, comment="Crawl scope, mapping profile, AI options"
    )
    auto_promote: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Promote high-confidence extractions without human review",
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    error_summary: Mapped[str | None] = mapped_column(Text)

    @property
    def progress_pct(self) -> float:
        if not self.total_items:
            return 0.0
        return round(100.0 * self.processed_items / self.total_items, 2)


class CrawlSchedule(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """Scheduled crawling / periodic web-search targets."""

    __tablename__ = "crawl_schedules"
    __table_args__ = (Index("ix_crawl_schedules_next_run", "is_active", "next_run_at"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(
        String(40), nullable=False, comment="url | sitemap | vendor_site | parallel_query"
    )
    target: Mapped[str] = mapped_column(String(2000), nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vendors.id", ondelete="SET NULL")
    )
    cron_expression: Mapped[str] = mapped_column(String(120), nullable=False, default="0 3 * * 1")
    max_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    include_patterns: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    exclude_patterns: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    auto_extract: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_status: Mapped[str | None] = mapped_column(String(40))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
