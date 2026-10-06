"""Requirement profiles, comparisons and vendor comparison."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentPrincipal, DbSession, require
from app.models.comparison import Comparison, ComparisonItem, RequirementProfile
from app.models.enums import AuditAction
from app.models.pump import Pump, PumpModel
from app.models.search import SearchIndex
from app.models.vendor import Vendor
from app.schemas.common import Message, Page
from app.schemas.comparison import (
    ComparisonCreate,
    ComparisonItemOut,
    ComparisonOut,
    RequirementProfileIn,
    RequirementProfileOut,
    VendorComparisonRow,
)
from app.services import audit, records
from app.services import comparison as comparison_service

router = APIRouter(tags=["comparisons"])


@router.get(
    "/requirement-profiles",
    response_model=Page[RequirementProfileOut],
    dependencies=[Depends(require("comparison", "read"))],
)
def list_profiles(
    db: DbSession,
    active_only: bool = True,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    stmt = select(RequirementProfile)
    if active_only:
        stmt = stmt.where(RequirementProfile.is_active.is_(True))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(RequirementProfile.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return Page[RequirementProfileOut](items=rows, total=int(total), limit=limit, offset=offset)


@router.post(
    "/requirement-profiles",
    response_model=RequirementProfileOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("comparison", "write"))],
)
def create_profile(
    payload: RequirementProfileIn, principal: CurrentPrincipal, db: DbSession
) -> RequirementProfile:
    """Define a requisition: duty point, hard requirements and scorecard weighting."""
    tenant_id = principal.require_tenant_id
    clash = db.scalar(
        select(RequirementProfile).where(
            RequirementProfile.tenant_id == tenant_id,
            RequirementProfile.name == payload.name,
        )
    )
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A profile named '{payload.name}' already exists"
        )

    profile = RequirementProfile(
        tenant_id=tenant_id,
        created_by_user_id=principal.user_id,
        **payload.model_dump(),
    )
    db.add(profile)
    audit.record_audit(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        entity_type="requirement_profiles",
        entity_label=payload.name,
        summary="Requirement profile created",
    )
    db.commit()
    db.refresh(profile)
    return profile


@router.get(
    "/requirement-profiles/{profile_id}",
    response_model=RequirementProfileOut,
    dependencies=[Depends(require("comparison", "read"))],
)
def get_profile(profile_id: uuid.UUID, db: DbSession) -> RequirementProfile:
    profile = db.get(RequirementProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement profile not found")
    return profile


@router.delete(
    "/requirement-profiles/{profile_id}",
    response_model=Message,
    dependencies=[Depends(require("comparison", "write"))],
)
def deactivate_profile(
    profile_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> Message:
    """Deactivate rather than delete, so past comparisons stay interpretable."""
    profile = db.get(RequirementProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement profile not found")
    profile.is_active = False
    audit.record_audit(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        entity_type="requirement_profiles",
        entity_id=profile.id,
        entity_label=profile.name,
        summary="Requirement profile deactivated",
    )
    db.commit()
    return Message(detail="Profile deactivated; existing comparisons are unaffected")


@router.post(
    "/pump-models/{pump_model_id}/score", dependencies=[Depends(require("comparison", "read"))]
)
def score_one(
    pump_model_id: uuid.UUID,
    db: DbSession,
    requirement_profile_id: uuid.UUID | None = Query(default=None),
) -> dict:
    """Score a single pump model, optionally against a requirement profile."""
    profile = db.get(RequirementProfile, requirement_profile_id) if requirement_profile_id else None
    if requirement_profile_id and profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Requirement profile not found")
    try:
        cards, _ = comparison_service.score_pump_model(db, pump_model_id, profile)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.commit()
    return {
        "pump_model_id": str(pump_model_id),
        "requirement_profile_id": str(profile.id) if profile else None,
        "scorecards": {
            name: {
                "score": card.score,
                "grade": card.grade,
                "fields_evaluated": card.fields_evaluated,
                "fields_missing": card.fields_missing,
                "disqualified": card.disqualified,
                "disqualification_reason": card.disqualification_reason,
                "breakdown": records.to_jsonable(card.breakdown()),
            }
            for name, card in cards.items()
        },
    }


@router.post(
    "/comparisons",
    response_model=ComparisonOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("comparison", "write"))],
)
def create_comparison(
    payload: ComparisonCreate, principal: CurrentPrincipal, db: DbSession
) -> ComparisonOut:
    """Score candidates side by side and freeze the result as a decision record."""
    if payload.comparison_kind == "vendor":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Use GET /vendor-comparison for vendor comparison; saved comparisons "
            "cover pump models.",
        )
    if not payload.pump_model_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Supply at least one pump_model_id")

    missing = [
        str(model_id) for model_id in payload.pump_model_ids if db.get(PumpModel, model_id) is None
    ]
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Unknown pump model id(s): {', '.join(missing)}"
        )

    comparison = comparison_service.build_comparison(
        db,
        tenant_id=principal.require_tenant_id,
        name=payload.name,
        description=payload.description,
        pump_model_ids=payload.pump_model_ids,
        requirement_profile_id=payload.requirement_profile_id,
        fields_shown=payload.fields_shown or None,
        principal=principal,
    )
    if payload.generate_narrative:
        comparison_service.generate_narrative(db, comparison, user_id=principal.user_id)

    audit.record_audit(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        entity_type="comparisons",
        entity_id=comparison.id,
        entity_label=comparison.name,
        summary=f"Comparison of {len(payload.pump_model_ids)} candidate(s) created",
    )
    db.commit()
    db.refresh(comparison)
    return _serialise_comparison(db, comparison)


@router.get(
    "/comparisons",
    response_model=Page[ComparisonOut],
    dependencies=[Depends(require("comparison", "read"))],
)
def list_comparisons(
    db: DbSession,
    status_filter: list[str] = Query(default_factory=list, alias="status"),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    stmt = select(Comparison)
    if status_filter:
        stmt = stmt.where(Comparison.status.in_(status_filter))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Comparison.created_at.desc()).limit(limit).offset(offset)).all()
    return Page[ComparisonOut](
        items=[_serialise_comparison(db, row) for row in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/comparisons/{comparison_id}",
    response_model=ComparisonOut,
    dependencies=[Depends(require("comparison", "read"))],
)
def get_comparison(comparison_id: uuid.UUID, db: DbSession) -> ComparisonOut:
    comparison = db.get(Comparison, comparison_id)
    if comparison is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comparison not found")
    return _serialise_comparison(db, comparison)


def _serialise_comparison(db: DbSession, comparison: Comparison) -> ComparisonOut:
    items = db.scalars(
        select(ComparisonItem)
        .where(ComparisonItem.comparison_id == comparison.id)
        .order_by(ComparisonItem.rank.asc().nullslast(), ComparisonItem.position)
    ).all()

    snapshot_rows = {
        row.get("pump_model_id"): row for row in (comparison.snapshot or {}).get("rows", [])
    }
    out_items: list[ComparisonItemOut] = []
    for item in items:
        row = snapshot_rows.get(str(item.pump_model_id), {})
        out_items.append(
            ComparisonItemOut(
                id=item.id,
                pump_model_id=item.pump_model_id,
                vendor_id=item.vendor_id,
                position=item.position,
                label=row.get("label"),
                technical_score=float(item.technical_score) if item.technical_score else None,
                commercial_score=float(item.commercial_score) if item.commercial_score else None,
                delivery_risk_score=(
                    float(item.delivery_risk_score) if item.delivery_risk_score else None
                ),
                data_confidence_score=(
                    float(item.data_confidence_score) if item.data_confidence_score else None
                ),
                overall_score=float(item.overall_score) if item.overall_score else None,
                rank=item.rank,
                disqualified=item.disqualified,
                disqualification_reason=item.disqualification_reason,
                score_breakdown=item.score_breakdown,
                values=row.get("values", {}),
            )
        )

    return ComparisonOut(
        id=comparison.id,
        name=comparison.name,
        description=comparison.description,
        comparison_kind=comparison.comparison_kind,
        requirement_profile_id=comparison.requirement_profile_id,
        status=comparison.status,
        recommendation=comparison.recommendation,
        ai_narrative=comparison.ai_narrative,
        fields_shown=comparison.fields_shown or [],
        items=out_items,
        snapshot=comparison.snapshot or {},
        created_at=comparison.created_at,
    )


@router.patch(
    "/comparisons/{comparison_id}",
    response_model=ComparisonOut,
    dependencies=[Depends(require("comparison", "write"))],
)
def finalise_comparison(
    comparison_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DbSession,
    recommendation: str | None = None,
    new_status: str | None = Query(
        default=None, alias="status", description="draft | final | archived"
    ),
) -> ComparisonOut:
    """Record the buyer's recommendation and lock the comparison."""
    from datetime import UTC, datetime

    comparison = db.get(Comparison, comparison_id)
    if comparison is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comparison not found")
    if comparison.status == "final" and new_status == "final":
        raise HTTPException(status.HTTP_409_CONFLICT, "Comparison is already final")

    if recommendation is not None:
        comparison.recommendation = recommendation
    if new_status:
        if new_status not in {"draft", "final", "archived"}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown status '{new_status}'")
        comparison.status = new_status
        if new_status == "final":
            comparison.finalised_at = datetime.now(UTC)

    audit.record_audit(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        entity_type="comparisons",
        entity_id=comparison.id,
        entity_label=comparison.name,
        summary=f"Comparison marked {comparison.status}",
        changes={"recommendation": {"to": recommendation}} if recommendation else {},
    )
    db.commit()
    db.refresh(comparison)
    return _serialise_comparison(db, comparison)


@router.post(
    "/comparisons/{comparison_id}/narrative", dependencies=[Depends(require("comparison", "write"))]
)
def regenerate_narrative(
    comparison_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> dict:
    """Regenerate the AI narrative from the frozen snapshot."""
    comparison = db.get(Comparison, comparison_id)
    if comparison is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comparison not found")
    narrative = comparison_service.generate_narrative(db, comparison, user_id=principal.user_id)
    db.commit()
    if narrative is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The AI provider is unavailable. Scores and the comparison itself are unaffected.",
        )
    return {"comparison_id": str(comparison_id), "ai_narrative": narrative}


# Deliberately NOT /comparisons/vendors: that path would be captured by
# /comparisons/{comparison_id} and fail UUID parsing before ever reaching here.
@router.get(
    "/vendor-comparison",
    response_model=list[VendorComparisonRow],
    dependencies=[Depends(require("comparison", "read"))],
)
def compare_vendors(
    db: DbSession,
    vendor_ids: list[uuid.UUID] = Query(min_length=1, max_length=12),
) -> list[VendorComparisonRow]:
    """Vendor-level comparison: governance, track record and portfolio breadth."""
    rows: list[VendorComparisonRow] = []
    for vendor_id in vendor_ids:
        vendor = db.get(Vendor, vendor_id)
        if vendor is None or vendor.deleted_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Vendor {vendor_id} not found")

        model_count = (
            db.scalar(
                select(func.count())
                .select_from(PumpModel)
                .join(Pump, Pump.id == PumpModel.pump_id)
                .where(Pump.vendor_id == vendor.id, PumpModel.deleted_at.is_(None))
            )
            or 0
        )
        aggregates = db.execute(
            select(
                func.avg(SearchIndex.standard_lead_time_weeks),
                func.min(SearchIndex.base_price_usd),
                func.avg(SearchIndex.data_completeness_pct),
                func.bool_or(SearchIndex.fpso_experience),
            ).where(SearchIndex.vendor_id == vendor.id)
        ).one()
        avg_lead_time, min_price, avg_completeness, fpso = aggregates

        certifications: list[str] = []
        for cert_list in db.scalars(
            select(SearchIndex.certifications).where(SearchIndex.vendor_id == vendor.id)
        ).all():
            for cert in cert_list or []:
                if cert not in certifications:
                    certifications.append(cert)

        rows.append(
            VendorComparisonRow(
                vendor_id=vendor.id,
                vendor_name=vendor.name,
                country=vendor.country or vendor.hq_country,
                vendor_tier=vendor.vendor_tier.value if vendor.vendor_tier else None,
                approval_status=(vendor.approval_status.value if vendor.approval_status else None),
                sanctions_status=(
                    vendor.sanctions_status.value if vendor.sanctions_status else None
                ),
                pump_model_count=int(model_count),
                fpso_experience=(fpso if fpso is not None else vendor.fpso_offshore_experience),
                on_time_delivery_pct=(
                    float(vendor.on_time_delivery_pct)
                    if vendor.on_time_delivery_pct is not None
                    else None
                ),
                total_units_supplied=vendor.total_units_supplied,
                qaqc_certifications=certifications[:25],
                data_completeness_pct=(
                    float(avg_completeness) if avg_completeness is not None else None
                ),
                avg_lead_time_weeks=float(avg_lead_time) if avg_lead_time is not None else None,
                min_price_usd=float(min_price) if min_price is not None else None,
            )
        )
    return rows
