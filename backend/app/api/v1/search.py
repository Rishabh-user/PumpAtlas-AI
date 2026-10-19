"""Search, filtering, facets and similar-pump matching."""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.core.deps import CurrentPrincipal, DbSession, require
from app.models.comparison import SavedSearch
from app.models.enums import (
    ApplicableStandard,
    AreaClassification,
    ConfidenceLevel,
    DriverType,
    Incoterm,
    PumpType,
    SealSystemType,
    VendorApprovalStatus,
    VendorTier,
    VerificationStatus,
)
from app.models.specs import TechnicalSpec
from app.schemas.common import Message
from app.schemas.search import SearchRequest, SearchResponse, SimilarRequest
from app.services import completeness, designations
from app.services import search as search_service

router = APIRouter(prefix="/search", tags=["search"])


def _to_filters(payload: SearchRequest) -> search_service.SearchFilters:
    data = payload.model_dump(exclude={"sort", "limit", "offset", "include_facets"})
    return search_service.SearchFilters(**data)


def _model_id(raw: Any) -> uuid.UUID | None:
    """A row's pump model id, however the index serialised it."""
    if raw is None:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def _model_ids(items: list[dict]) -> list[uuid.UUID]:
    seen = [_model_id(item.get("pump_model_id")) for item in items]
    return [value for value in seen if value is not None]


def _attach_model_kind(items: list[dict]) -> None:
    """Say what each row names: a product, an approval line, a placeholder, a type code.

    Costs no query - it reads `model_code`, which the index already carries. It is
    attached rather than worked out in the browser because the classifier is the same
    one the profile page and `scripts.pending_pumps` use, and a second copy in
    TypeScript would drift the first time a new shape of junk designation turned up.

    Only a product has a datasheet, so this is what tells the list which records a web
    search can do anything for: 67 of 160, the rest being approved-suppliers lines,
    resolver placeholders and bare API 610 type codes.
    """
    for item in items:
        code = item.get("model_code")
        if isinstance(code, str):
            item["model_kind"] = designations.searchability(code).value


def _attach_coverage(db: DbSession, items: list[dict]) -> None:
    """Add `spec_coverage` to each row, in one round trip for the whole page.

    Computed rather than indexed: putting it in `search_index` would mean a migration
    and a reindex, and would go stale the moment a spec was written. One extra query
    per page is the cheaper trade.
    """
    ids = _model_ids(items)
    if not ids:
        return
    coverage = completeness.coverage_for_models(db, ids)
    for row in items:
        key = _model_id(row.get("pump_model_id"))
        if key is not None and key in coverage:
            row["spec_coverage"] = coverage[key]


#: What the list shows, and the range columns that hold the same quantity when there is
#: no single rated figure. A model that comes in 45 sizes has a performance envelope,
#: not a duty point - a rated capacity exists only once a size is chosen for a duty.
_ENVELOPE = {
    "capacity": ("rated_capacity_m3h", "min_capacity_m3h", "max_capacity_m3h"),
    "head": ("rated_head_m", None, "max_head_m"),
    "efficiency": ("hydraulic_efficiency_pct", None, "bep_efficiency_pct"),
    "speed": ("rated_speed_rpm", "min_speed_rpm", "max_speed_rpm"),
    "power": ("rated_power_kw", None, "max_power_kw"),
}


def _attach_duty_envelope(db: DbSession, items: list[dict]) -> None:
    """Add the performance envelope for the rows on this page.

    `search_index` carries only the `rated_*` figures, so a record whose datasheet gave
    "flow to 1,000 m3/h, head to 150 m" showed an em dash in every duty column. Of 78
    technical spec rows, 6 hold a rated capacity and 56 hold a maximum - so nine out of
    ten blank capacity cells were blank because the list asked the wrong column, not
    because nobody had recorded anything.

    The index cannot answer this without new columns and a reindex, so it is read from
    the spec rows for the page being rendered: one query, a handful of rows.
    """
    ids = _model_ids(items)
    if not ids:
        return
    wanted = sorted(
        {name for trio in _ENVELOPE.values() for name in trio if name is not None}
    )
    columns = [TechnicalSpec.__table__.c[name] for name in wanted]
    rows = db.execute(
        select(TechnicalSpec.pump_model_id, *columns).where(
            TechnicalSpec.is_current.is_(True),
            TechnicalSpec.pump_model_id.in_(ids),
        )
    ).all()
    by_model = {row[0]: dict(zip(wanted, row[1:], strict=True)) for row in rows}
    for item in items:
        key = _model_id(item.get("pump_model_id"))
        held = by_model.get(key)
        if not held:
            continue
        item["duty_envelope"] = {
            quantity: {
                "rated": held.get(rated),
                "min": held.get(low) if low else None,
                "max": held.get(high) if high else None,
            }
            for quantity, (rated, low, high) in _ENVELOPE.items()
        }


@router.post("", response_model=SearchResponse, dependencies=[Depends(require("search", "read"))])
def search(payload: SearchRequest, db: DbSession) -> SearchResponse:
    """Full-text search across every indexed record, with structured filters.

    Tenant isolation is enforced by row level security on ``search_index``, so results
    never cross a tenant boundary regardless of the filters supplied.
    """
    started = time.perf_counter()
    filters = _to_filters(payload)
    try:
        items, total = search_service.search_pump_models(
            db, filters, sort=payload.sort, limit=payload.limit, offset=payload.offset
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    # Per-group coverage for the rows on this page, in one query. The index carries a
    # single percentage against 437 tracked fields, which renders a well-documented
    # pump as "6.4%" and leaves it indistinguishable from an empty row.
    _attach_coverage(db, items)
    _attach_duty_envelope(db, items)
    _attach_model_kind(items)

    facets = search_service.facet_counts(db, filters) if payload.include_facets else {}
    return SearchResponse(
        items=items,
        total=total,
        limit=payload.limit,
        offset=payload.offset,
        sort=payload.sort,
        facets=facets,
        took_ms=int((time.perf_counter() - started) * 1000),
    )


@router.get("", response_model=SearchResponse, dependencies=[Depends(require("search", "read"))])
def quick_search(
    db: DbSession,
    q: str | None = Query(default=None, description="Free-text query"),
    pump_type: list[str] = Query(default_factory=list),
    country: list[str] = Query(default_factory=list),
    standard: list[str] = Query(default_factory=list),
    capacity_min: float | None = None,
    capacity_max: float | None = None,
    head_min: float | None = None,
    head_max: float | None = None,
    price_max: float | None = None,
    lead_time_max: float | None = None,
    sort: str = "relevance",
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> SearchResponse:
    """GET form of the search endpoint, for shareable links and simple integrations."""
    payload = SearchRequest(
        query=q,
        pump_types=pump_type,
        countries=country,
        standards=standard,
        capacity_min=capacity_min,
        capacity_max=capacity_max,
        head_min=head_min,
        head_max=head_max,
        price_max=price_max,
        lead_time_max=lead_time_max,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return search(payload, db)


@router.post(
    "/similar/{pump_model_id}",
    dependencies=[Depends(require("search", "read"))],
)
def similar_pumps(pump_model_id: uuid.UUID, payload: SimilarRequest, db: DbSession) -> dict:
    """Alternatives with a comparable duty point - the "what else fits?" query."""
    matches = search_service.find_similar_pump_models(
        db,
        pump_model_id,
        limit=payload.limit,
        duty_tolerance_pct=payload.duty_tolerance_pct,
    )
    return {"anchor_pump_model_id": str(pump_model_id), "items": matches, "total": len(matches)}


@router.get("/filters/options", dependencies=[Depends(require("search", "read"))])
def filter_options() -> dict:
    """Controlled vocabularies for the filter sidebar, straight from the DB enums."""
    return {
        "pump_types": [e.value for e in PumpType],
        "standards": [e.value for e in ApplicableStandard],
        "area_classifications": [e.value for e in AreaClassification],
        "seal_system_types": [e.value for e in SealSystemType],
        "driver_types": [e.value for e in DriverType],
        "incoterms": [e.value for e in Incoterm],
        "vendor_approval_statuses": [e.value for e in VendorApprovalStatus],
        "vendor_tiers": [e.value for e in VendorTier],
        "confidence_levels": [e.value for e in ConfidenceLevel],
        "verification_statuses": [e.value for e in VerificationStatus],
        "sort_options": sorted(search_service.SORT_OPTIONS),
    }


@router.get("/saved", dependencies=[Depends(require("search", "read"))])
def list_saved_searches(principal: CurrentPrincipal, db: DbSession) -> list[dict]:
    rows = db.scalars(
        select(SavedSearch)
        .where(
            (SavedSearch.created_by_user_id == principal.user_id)
            | (SavedSearch.is_shared_in_tenant.is_(True))
        )
        .order_by(SavedSearch.updated_at.desc())
    ).all()
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "query_text": row.query_text,
            "filters": row.filters,
            "sort_by": row.sort_by,
            "is_shared_in_tenant": row.is_shared_in_tenant,
            "alert_enabled": row.alert_enabled,
            "last_result_count": row.last_result_count,
        }
        for row in rows
    ]


@router.post(
    "/saved", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require("search", "read"))]
)
def save_search(
    payload: SearchRequest,
    principal: CurrentPrincipal,
    db: DbSession,
    name: str = Query(min_length=2, max_length=255),
    share_in_tenant: bool = False,
) -> dict:
    """Store a query + filter set so an analyst can re-run it or alert on it."""
    filters = _to_filters(payload)
    _, total = search_service.search_pump_models(db, filters, sort=payload.sort, limit=1)
    row = SavedSearch(
        tenant_id=principal.tenant_id,
        name=name,
        query_text=payload.query,
        filters=payload.model_dump(mode="json", exclude={"limit", "offset", "include_facets"}),
        sort_by=payload.sort,
        is_shared_in_tenant=share_in_tenant,
        last_result_count=total,
        created_by_user_id=principal.user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "name": row.name, "result_count": total}


@router.delete(
    "/saved/{saved_id}", response_model=Message, dependencies=[Depends(require("search", "read"))]
)
def delete_saved_search(saved_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> Message:
    row = db.get(SavedSearch, saved_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved search not found")
    if row.created_by_user_id != principal.user_id and not principal.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner may delete this search")
    db.delete(row)
    db.commit()
    return Message(detail="Saved search deleted")
