"""Search, filtering, facets and similar-pump matching."""

from __future__ import annotations

import time
import uuid

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
from app.schemas.common import Message
from app.schemas.search import SearchRequest, SearchResponse, SimilarRequest
from app.services import search as search_service

router = APIRouter(prefix="/search", tags=["search"])


def _to_filters(payload: SearchRequest) -> search_service.SearchFilters:
    data = payload.model_dump(exclude={"sort", "limit", "offset", "include_facets"})
    return search_service.SearchFilters(**data)


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
