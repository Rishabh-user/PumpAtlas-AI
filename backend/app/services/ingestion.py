"""Ingestion: fetch, store and register sources.

Every path into the platform - upload, URL, crawl, API sync, manual form, Parallel AI
result - lands in ``sources`` first. Extraction is a separate, retryable step, so a
parsing failure never loses the captured evidence.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import timeouts
from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import (
    ConfidenceLevel,
    DocumentKind,
    IngestionStatus,
    SourceType,
)
from app.models.source import Document, ImportBatch, Source
from app.services import parsing
from app.services.storage import build_key, get_storage

log = get_logger(__name__)

# Publisher trust used as the starting reliability score. OEM domains earn the top
# band once a vendor record confirms the domain; everything else starts lower.
RELIABILITY_BY_SOURCE_TYPE = {
    SourceType.MANUAL_FORM: 0.75,
    SourceType.VENDOR_PORTAL: 0.85,
    SourceType.PDF: 0.70,
    SourceType.DOCUMENT: 0.65,
    SourceType.SPREADSHEET: 0.65,
    SourceType.API: 0.80,
    SourceType.WEB_PAGE: 0.55,
    SourceType.PARALLEL_SEARCH: 0.50,
    SourceType.EMAIL: 0.55,
}

DOCUMENT_KIND_HINTS = (
    ("datasheet", DocumentKind.DATASHEET),
    ("data sheet", DocumentKind.DATASHEET),
    ("curve", DocumentKind.PERFORMANCE_CURVE),
    ("quotation", DocumentKind.QUOTATION),
    ("quote", DocumentKind.QUOTATION),
    ("offer", DocumentKind.QUOTATION),
    ("certificate", DocumentKind.CERTIFICATE),
    ("cert", DocumentKind.CERTIFICATE),
    ("test report", DocumentKind.TEST_REPORT),
    ("fat", DocumentKind.TEST_REPORT),
    ("manual", DocumentKind.MANUAL),
    ("iom", DocumentKind.MANUAL),
    ("reference", DocumentKind.REFERENCE_LIST),
    ("track record", DocumentKind.REFERENCE_LIST),
    ("ga drawing", DocumentKind.GA_DRAWING),
    ("outline", DocumentKind.GA_DRAWING),
    ("profile", DocumentKind.COMPANY_PROFILE),
    ("financial", DocumentKind.FINANCIAL_STATEMENT),
    ("annual report", DocumentKind.FINANCIAL_STATEMENT),
)


class IngestionError(RuntimeError):
    pass


def guess_document_kind(filename: str, mime_type: str | None = None) -> DocumentKind:
    lowered = filename.lower()
    for needle, kind in DOCUMENT_KIND_HINTS:
        if needle in lowered:
            return kind
    if lowered.endswith((".xlsx", ".xlsm", ".csv")):
        return DocumentKind.SPREADSHEET
    if mime_type == parsing.PDF_MIME or lowered.endswith(".pdf"):
        return DocumentKind.DATASHEET
    return DocumentKind.OTHER


def source_type_for_filename(filename: str, mime_type: str | None = None) -> SourceType:
    lowered = filename.lower()
    if lowered.endswith(".pdf") or mime_type == parsing.PDF_MIME:
        return SourceType.PDF
    if lowered.endswith((".xlsx", ".xlsm", ".csv", ".tsv")):
        return SourceType.SPREADSHEET
    if lowered.endswith((".docx", ".doc")):
        return SourceType.DOCUMENT
    if lowered.endswith((".html", ".htm")):
        return SourceType.WEB_PAGE
    return SourceType.DOCUMENT


def content_hash(data: bytes | str) -> str:
    payload = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(payload).hexdigest()


def find_duplicate_source(db: Session, tenant_id: uuid.UUID | None, digest: str) -> Source | None:
    """A re-crawl of unchanged content must not create a second source row."""
    return db.scalar(
        select(Source).where(
            Source.tenant_id == tenant_id,
            Source.content_hash == digest,
            Source.deleted_at.is_(None),
        )
    )


def robots_allows(url: str, user_agent: str | None = None) -> bool:
    """Respect robots.txt for scheduled crawling. Failures are treated as allowed."""
    if not settings.CRAWL_RESPECT_ROBOTS:
        return True
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = RobotFileParser()
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            response = client.get(robots_url, headers={"User-Agent": settings.CRAWL_USER_AGENT})
        if response.status_code >= 400:
            return True
        parser.parse(response.text.splitlines())
    except (httpx.HTTPError, ValueError):
        return True
    return parser.can_fetch(user_agent or settings.CRAWL_USER_AGENT, url)


def fetch_url(url: str, *, timeout: int = 45) -> tuple[bytes, dict[str, str], int]:
    """GET a URL with the platform's crawl identity. Returns (body, headers, status)."""
    with httpx.Client(
        # Bounded per phase. A page fetch is the one call in this pipeline aimed at a
        # server nobody vetted, so it is also the one most likely to accept a connection
        # and then trickle - and `timeout=45` alone restarts its read clock on every byte.
        timeout=timeouts.bounded(timeout),
        follow_redirects=True,
        headers={
            "User-Agent": settings.CRAWL_USER_AGENT,
            "Accept": "text/html,application/pdf,application/xhtml+xml,*/*",
        },
    ) as client:
        response = client.get(url)
    if len(response.content) > settings.CRAWL_MAX_PAGE_BYTES:
        raise IngestionError(
            f"Response exceeds CRAWL_MAX_PAGE_BYTES ({len(response.content)} bytes)"
        )
    return response.content, dict(response.headers), response.status_code


def create_batch(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    name: str,
    import_mode: str,
    source_type: SourceType,
    total_items: int = 0,
    config: dict | None = None,
    auto_promote: bool = False,
    created_by_user_id: uuid.UUID | None = None,
) -> ImportBatch:
    batch = ImportBatch(
        tenant_id=tenant_id,
        name=name,
        import_mode=import_mode,
        source_type=source_type,
        status=IngestionStatus.QUEUED,
        total_items=total_items,
        config=config or {},
        auto_promote=auto_promote,
        created_by_user_id=created_by_user_id,
    )
    db.add(batch)
    db.flush()
    return batch


def register_upload(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    filename: str,
    data: bytes,
    mime_type: str | None = None,
    vendor_hint: str | None = None,
    vendor_id: uuid.UUID | None = None,
    pump_model_id: uuid.UUID | None = None,
    document_kind: DocumentKind | None = None,
    batch: ImportBatch | None = None,
    user_id: uuid.UUID | None = None,
    confidence_level: ConfidenceLevel = ConfidenceLevel.VENDOR_DECLARED,
) -> tuple[Source, Document]:
    """Store an uploaded file, parse it and register the source + document rows."""
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise IngestionError(f"File exceeds the {settings.MAX_UPLOAD_MB} MB upload limit")

    digest = content_hash(data)
    parsed = parsing.parse_bytes(data, filename=filename, mime_type=mime_type)
    stored = get_storage().put(build_key(tenant_id, filename), data, content_type=mime_type)
    now = datetime.now(UTC)
    stype = source_type_for_filename(filename, mime_type)

    source = Source(
        tenant_id=tenant_id,
        source_type=stype,
        status=IngestionStatus.PARSED if parsed.text else IngestionStatus.NEEDS_REVIEW,
        title=parsed.metadata.get("title") or filename,
        publisher=parsed.metadata.get("publisher"),
        author=parsed.metadata.get("author"),
        captured_at=now,
        content_type=mime_type,
        content_hash=digest,
        parsed_text=parsed.text,
        parsed_text_chars=parsed.char_count,
        source_metadata={
            "filename": filename,
            "parser_warnings": parsed.warnings,
            "parser_metadata": {k: v for k, v in parsed.metadata.items() if k != "title"},
            "content": parsed.content or None,
        },
        confidence_level=confidence_level,
        reliability_score=RELIABILITY_BY_SOURCE_TYPE.get(stype, 0.6),
        is_authoritative=confidence_level
        in {ConfidenceLevel.VERIFIED, ConfidenceLevel.VENDOR_DECLARED},
        import_batch_id=batch.id if batch else None,
        submitted_by_user_id=user_id,
        vendor_hint=vendor_hint,
        processed_at=now,
    )
    db.add(source)
    db.flush()

    document = Document(
        tenant_id=tenant_id,
        source_id=source.id,
        vendor_id=vendor_id,
        pump_model_id=pump_model_id,
        document_kind=document_kind or guess_document_kind(filename, mime_type),
        filename=filename,
        storage_key=stored.key,
        storage_bucket=stored.bucket,
        mime_type=mime_type,
        size_bytes=stored.size_bytes,
        checksum_sha256=stored.checksum_sha256,
        page_count=parsed.page_count,
        extracted_text=parsed.text,
        uploaded_by_user_id=user_id,
        doc_metadata=parsed.metadata,
    )
    db.add(document)
    db.flush()
    log.info(
        "ingestion.upload_registered",
        source_id=str(source.id),
        filename=filename,
        chars=parsed.char_count,
    )
    return source, document


def refresh_parse(db: Session, source: Source) -> bool:
    """Re-derive a stored page's text and capture when the parser has moved on.

    Deduplication by content hash means a page captured last week is handed back as-is,
    including the text it was reduced to under the parser of the day. So a parser
    improvement never reached anything already captured: keeping the footer was pointless
    for every source in the database, and re-running an enrichment produced the same
    empty fields for a reason nobody could see from the outside.

    Re-parses from the stored HTML, so it costs no request and cannot fail differently
    from the original capture. Returns whether it did anything.
    """
    metadata = dict(source.source_metadata or {})
    if metadata.get("parser_version") == parsing.PARSER_VERSION:
        return False
    if not source.raw_content:
        # A binary lives in object storage, not in the row; leave it alone.
        metadata["parser_version"] = parsing.PARSER_VERSION
        source.source_metadata = metadata
        return False

    parsed = parsing.parse_bytes(
        source.raw_content.encode("utf-8", errors="replace"),
        filename=urlparse(source.source_url or "").path or None,
        mime_type=source.content_type,
    )
    if not parsed.text:
        return False

    source.parsed_text = parsed.text
    source.parsed_text_chars = parsed.char_count
    metadata["content"] = parsed.content or None
    metadata["parser_warnings"] = parsed.warnings
    metadata["parser_version"] = parsing.PARSER_VERSION
    source.source_metadata = metadata
    db.flush()
    return True


def register_url(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    url: str,
    vendor_hint: str | None = None,
    batch: ImportBatch | None = None,
    user_id: uuid.UUID | None = None,
    skip_if_unchanged: bool = True,
    store_binary_documents: bool = True,
) -> Source:
    """Fetch a web page or linked document and register it as a source."""
    if not robots_allows(url):
        raise IngestionError(f"robots.txt disallows crawling {url}")

    body, headers, status_code = fetch_url(url)
    digest = content_hash(body)

    if skip_if_unchanged:
        existing = find_duplicate_source(db, tenant_id, digest)
        if existing is not None:
            existing.captured_at = datetime.now(UTC)
            refreshed = refresh_parse(db, existing)
            log.info(
                "ingestion.url_unchanged",
                url=url,
                source_id=str(existing.id),
                reparsed=refreshed,
            )
            return existing

    mime_type = (headers.get("content-type") or "").split(";")[0].strip() or None
    parsed = parsing.parse_bytes(body, filename=urlparse(url).path, mime_type=mime_type)
    is_binary = bool(mime_type and not mime_type.startswith(("text/", "application/json")))
    now = datetime.now(UTC)
    stype = SourceType.PDF if mime_type == parsing.PDF_MIME else SourceType.WEB_PAGE

    source = Source(
        tenant_id=tenant_id,
        source_type=stype,
        status=IngestionStatus.PARSED if parsed.text else IngestionStatus.NEEDS_REVIEW,
        title=parsed.metadata.get("title") or url,
        source_url=url,
        canonical_url=url,
        publisher=parsed.metadata.get("publisher") or urlparse(url).netloc,
        author=parsed.metadata.get("author"),
        captured_at=now,
        http_status=status_code,
        content_type=mime_type,
        content_hash=digest,
        # Raw HTML is kept for re-parsing; binaries live in object storage instead.
        raw_content=None if is_binary else body.decode("utf-8", errors="replace")[:2_000_000],
        parsed_text=parsed.text,
        parsed_text_chars=parsed.char_count,
        source_metadata={
            "headers": {
                k: v
                for k, v in headers.items()
                if k.lower() in {"content-type", "last-modified", "etag", "content-length"}
            },
            "parser_warnings": parsed.warnings,
            "document_links": parsed.metadata.get("document_links", []),
            # The page as structure: headings, paragraphs, tables, lists, links,
            # documents and contact details. `parsed_text` is what the reading model is
            # given and loses all of that shape - a certification list becomes prose, a
            # specification table becomes a run of words - so the capture is kept too.
            # It makes a page re-readable without re-fetching it, which matters when the
            # site has changed or blocks a second visit.
            "content": parsed.content or None,
            "parser_version": parsing.PARSER_VERSION,
        },
        confidence_level=ConfidenceLevel.THIRD_PARTY,
        reliability_score=RELIABILITY_BY_SOURCE_TYPE.get(stype, 0.55),
        import_batch_id=batch.id if batch else None,
        submitted_by_user_id=user_id,
        vendor_hint=vendor_hint,
        processed_at=now,
    )
    db.add(source)
    db.flush()

    if is_binary and store_binary_documents:
        filename = urlparse(url).path.rsplit("/", 1)[-1] or "download"
        stored = get_storage().put(build_key(tenant_id, filename), body, content_type=mime_type)
        db.add(
            Document(
                tenant_id=tenant_id,
                source_id=source.id,
                document_kind=guess_document_kind(filename, mime_type),
                filename=filename,
                storage_key=stored.key,
                storage_bucket=stored.bucket,
                mime_type=mime_type,
                size_bytes=stored.size_bytes,
                checksum_sha256=stored.checksum_sha256,
                page_count=parsed.page_count,
                extracted_text=parsed.text,
                uploaded_by_user_id=user_id,
                doc_metadata={"origin_url": url},
            )
        )
    log.info("ingestion.url_registered", url=url, source_id=str(source.id), status=status_code)
    return source


def register_manual_submission(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    title: str,
    payload: dict,
    user_id: uuid.UUID | None = None,
    submitted_by_organisation: str | None = None,
    confidence_level: ConfidenceLevel = ConfidenceLevel.VENDOR_DECLARED,
) -> Source:
    """A form submission is a source too - it must be as traceable as a crawl."""
    rendered = "\n".join(f"{key}: {value}" for key, value in payload.items() if value is not None)
    now = datetime.now(UTC)
    source = Source(
        tenant_id=tenant_id,
        source_type=SourceType.MANUAL_FORM,
        status=IngestionStatus.PARSED,
        title=title,
        publisher=submitted_by_organisation,
        captured_at=now,
        content_hash=content_hash(rendered),
        raw_content=None,
        parsed_text=rendered,
        parsed_text_chars=len(rendered),
        source_metadata={"submitted_payload": payload},
        confidence_level=confidence_level,
        reliability_score=RELIABILITY_BY_SOURCE_TYPE[SourceType.MANUAL_FORM],
        is_authoritative=True,
        submitted_by_user_id=user_id,
        processed_at=now,
    )
    db.add(source)
    db.flush()
    return source


def register_search_result(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    url: str,
    title: str | None,
    excerpt: str,
    search_id: str | None,
    rank: int | None,
    batch: ImportBatch | None = None,
    user_id: uuid.UUID | None = None,
) -> Source:
    """Store a Parallel AI hit. The excerpt is evidence even before the page is fetched."""
    now = datetime.now(UTC)
    source = Source(
        tenant_id=tenant_id,
        source_type=SourceType.PARALLEL_SEARCH,
        status=IngestionStatus.PARSED if excerpt else IngestionStatus.QUEUED,
        title=title or url,
        source_url=url,
        publisher=urlparse(url).netloc,
        captured_at=now,
        content_hash=content_hash(f"{url}:{excerpt}"),
        parsed_text=excerpt,
        parsed_text_chars=len(excerpt),
        source_metadata={"parallel_search_id": search_id, "rank": rank},
        confidence_level=ConfidenceLevel.THIRD_PARTY,
        reliability_score=RELIABILITY_BY_SOURCE_TYPE[SourceType.PARALLEL_SEARCH],
        parallel_search_id=search_id,
        parallel_result_rank=rank,
        import_batch_id=batch.id if batch else None,
        submitted_by_user_id=user_id,
        processed_at=now,
    )
    db.add(source)
    db.flush()
    return source


def extract_document_links(source: Source, limit: int = 25) -> list[str]:
    """Datasheet links found on a crawled page, absolutised for follow-up fetching."""
    links = (source.source_metadata or {}).get("document_links") or []
    base = source.source_url or ""
    return [urljoin(base, link) for link in links[:limit]]
