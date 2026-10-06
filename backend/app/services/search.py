"""Search and filtering over ``search_index``.

PostgreSQL full-text search with weighted ranking, plus the structured filters the
procurement and engineering screens need. Similar-pump matching is a hydraulic-distance
query, not a text query - two pumps are similar when their duty points are close and
their type and materials agree.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, func, or_, select, text
from sqlalchemy.orm import Session

from app.models.search import SearchIndex

# Sort keys the API accepts, mapped to columns. Anything else is rejected rather than
# interpolated, so sort order can never become an injection vector.
SORT_OPTIONS: dict[str, Any] = {
    "relevance": None,
    "price_asc": SearchIndex.base_price_usd.asc().nullslast(),
    "price_desc": SearchIndex.base_price_usd.desc().nullslast(),
    "lead_time_asc": SearchIndex.standard_lead_time_weeks.asc().nullslast(),
    "lead_time_desc": SearchIndex.standard_lead_time_weeks.desc().nullslast(),
    "capacity_asc": SearchIndex.rated_capacity_m3h.asc().nullslast(),
    "capacity_desc": SearchIndex.rated_capacity_m3h.desc().nullslast(),
    "head_desc": SearchIndex.rated_head_m.desc().nullslast(),
    "efficiency_desc": SearchIndex.hydraulic_efficiency_pct.desc().nullslast(),
    "weight_asc": SearchIndex.dry_weight_kg.asc().nullslast(),
    "confidence_desc": SearchIndex.data_confidence_score.desc().nullslast(),
    "completeness_desc": SearchIndex.data_completeness_pct.desc().nullslast(),
    # "What still needs work" - the question the completeness figure is most often asked.
    # Nulls last: a record with no figure yet is unknown, not empty, and leading with
    # unknowns would bury the ones actually known to be thin.
    "completeness_asc": SearchIndex.data_completeness_pct.asc().nullslast(),
    "vendor_asc": SearchIndex.vendor_name.asc(),
    "newest": SearchIndex.updated_at.desc(),
}


@dataclass
class SearchFilters:
    """Every filter the search screen exposes. All optional, all AND-combined."""

    query: str | None = None
    countries: list[str] = field(default_factory=list)
    vendor_ids: list[uuid.UUID] = field(default_factory=list)
    vendor_name: str | None = None
    pump_types: list[str] = field(default_factory=list)
    standards: list[str] = field(default_factory=list)
    service_application: str | None = None
    certifications: list[str] = field(default_factory=list)
    area_classifications: list[str] = field(default_factory=list)
    seal_system_types: list[str] = field(default_factory=list)
    driver_types: list[str] = field(default_factory=list)
    material_classes: list[str] = field(default_factory=list)
    incoterms: list[str] = field(default_factory=list)
    vendor_approval_statuses: list[str] = field(default_factory=list)
    vendor_tiers: list[str] = field(default_factory=list)
    countries_of_origin: list[str] = field(default_factory=list)

    capacity_min: Decimal | None = None
    capacity_max: Decimal | None = None
    head_min: Decimal | None = None
    head_max: Decimal | None = None
    npshr_max: Decimal | None = None
    efficiency_min: Decimal | None = None
    speed_min: int | None = None
    speed_max: int | None = None
    power_min: Decimal | None = None
    power_max: Decimal | None = None
    temperature_max: Decimal | None = None
    design_pressure_min: Decimal | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    lead_time_max: Decimal | None = None
    weight_max: Decimal | None = None
    footprint_max: Decimal | None = None
    otd_min: Decimal | None = None
    completeness_min: Decimal | None = None

    fpso_experience: bool | None = None
    nace_compliant: bool | None = None
    confidence_levels: list[str] = field(default_factory=list)
    verification_statuses: list[str] = field(default_factory=list)
    max_open_flags: int | None = None
    include_shared_master: bool = True
    only_shared_master: bool = False


def build_tsquery(raw: str) -> Any:
    """Turn user input into a safe tsquery.

    ``websearch_to_tsquery`` handles quoted phrases, OR and negation without ever
    letting the input reach the SQL parser, which is what makes free-text search safe
    to expose directly to the search bar.
    """
    return func.websearch_to_tsquery("pumpatlas", raw)


def apply_filters(stmt: Select, filters: SearchFilters) -> Select:
    """Attach every structured predicate. Empty filters add no clauses."""
    conditions: list[Any] = []

    def in_list(column: Any, values: list[Any], transform=None) -> None:
        if values:
            prepared = [transform(v) if transform else v for v in values]
            conditions.append(column.in_(prepared))

    in_list(SearchIndex.vendor_country, filters.countries, lambda v: str(v).upper()[:2])
    in_list(
        SearchIndex.country_of_origin, filters.countries_of_origin, lambda v: str(v).upper()[:2]
    )
    in_list(SearchIndex.vendor_id, filters.vendor_ids)
    in_list(SearchIndex.pump_type, filters.pump_types)
    in_list(SearchIndex.applicable_standard, filters.standards)
    in_list(SearchIndex.area_classification, filters.area_classifications)
    in_list(SearchIndex.seal_system_type, filters.seal_system_types)
    in_list(SearchIndex.driver_type, filters.driver_types)
    in_list(SearchIndex.material_class, filters.material_classes)
    in_list(SearchIndex.vendor_approval_status, filters.vendor_approval_statuses)
    in_list(SearchIndex.vendor_tier, filters.vendor_tiers)
    in_list(SearchIndex.confidence_level, filters.confidence_levels)
    in_list(SearchIndex.verification_status, filters.verification_statuses)

    if filters.vendor_name:
        conditions.append(SearchIndex.vendor_name.ilike(f"%{filters.vendor_name}%"))
    if filters.service_application:
        conditions.append(SearchIndex.service_application.ilike(f"%{filters.service_application}%"))
    if filters.certifications:
        # Array overlap: match any of the requested certifications, case-insensitively.
        lowered = [c.lower() for c in filters.certifications]
        conditions.append(
            func.lower(func.array_to_string(SearchIndex.certifications, "|")).op("~")(
                "|".join(lowered)
            )
        )
    if filters.incoterms:
        conditions.append(
            SearchIndex.incoterms_offered.overlap([i.lower() for i in filters.incoterms])
        )

    ranges = (
        (SearchIndex.rated_capacity_m3h, filters.capacity_min, filters.capacity_max),
        (SearchIndex.rated_head_m, filters.head_min, filters.head_max),
        (SearchIndex.rated_speed_rpm, filters.speed_min, filters.speed_max),
        (SearchIndex.rated_power_kw, filters.power_min, filters.power_max),
        (SearchIndex.base_price_usd, filters.price_min, filters.price_max),
    )
    for column, low, high in ranges:
        if low is not None:
            conditions.append(column >= low)
        if high is not None:
            conditions.append(column <= high)

    ceilings = (
        (SearchIndex.npsh_required_m, filters.npshr_max),
        (SearchIndex.standard_lead_time_weeks, filters.lead_time_max),
        (SearchIndex.dry_weight_kg, filters.weight_max),
        (SearchIndex.footprint_area_m2, filters.footprint_max),
        (SearchIndex.fluid_temperature_max_c, filters.temperature_max),
    )
    for column, ceiling in ceilings:
        if ceiling is not None:
            conditions.append(column <= ceiling)

    floors = (
        (SearchIndex.hydraulic_efficiency_pct, filters.efficiency_min),
        (SearchIndex.casing_design_pressure_barg, filters.design_pressure_min),
        (SearchIndex.on_time_delivery_pct, filters.otd_min),
        (SearchIndex.data_completeness_pct, filters.completeness_min),
    )
    for column, floor in floors:
        if floor is not None:
            conditions.append(column >= floor)

    if filters.fpso_experience is not None:
        conditions.append(SearchIndex.fpso_experience.is_(filters.fpso_experience))
    if filters.nace_compliant is not None:
        conditions.append(SearchIndex.nace_compliant.is_(filters.nace_compliant))
    if filters.max_open_flags is not None:
        conditions.append(SearchIndex.open_flag_count <= filters.max_open_flags)

    if filters.only_shared_master:
        conditions.append(SearchIndex.is_shared_master.is_(True))
    elif not filters.include_shared_master:
        conditions.append(SearchIndex.is_shared_master.is_(False))

    return stmt.where(and_(*conditions)) if conditions else stmt


def search_pump_models(
    db: Session,
    filters: SearchFilters,
    *,
    sort: str = "relevance",
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Run a search. Returns ``(rows, total_count)``.

    Tenant scoping is enforced by row level security on ``search_index``, so no
    tenant predicate is added here - that avoids the classic bug where one query
    forgets the filter and leaks across tenants.
    """
    if sort not in SORT_OPTIONS:
        raise ValueError(f"Unsupported sort key {sort!r}. Allowed: {sorted(SORT_OPTIONS)}")

    rank = None
    stmt = select(SearchIndex)
    if filters.query:
        tsquery = build_tsquery(filters.query)
        rank = func.ts_rank_cd(SearchIndex.search_vector, tsquery)
        stmt = stmt.where(
            or_(
                SearchIndex.search_vector.op("@@")(tsquery),
                # Trigram fallback, for model codes the stemmer mangles ("HPX4x6")
                # and for a misspelled vendor name.
                #
                # `word_similarity`, not `similarity`. The latter compares the query
                # against the *whole* label — "Sulzer - OCV range of API 610 type VS4
                # sump pumps - OCV" — so a short query scores near zero however well
                # it matches one word of it, and measured against this catalogue the
                # clause admitted 0 rows for every query tried, including exact ones.
                # It was a fallback that could never fire.
                #
                # `word_similarity(query, label)` scores the query against the best
                # matching run of words instead, which is what a typo needs: "sulzr"
                # reaches 13 records where `similarity` reached none, and nonsense
                # still matches nothing.
                func.word_similarity(filters.query, SearchIndex.label) > 0.25,
            )
        )

    stmt = apply_filters(stmt, filters)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    if sort == "relevance" and rank is not None:
        stmt = stmt.order_by(rank.desc(), SearchIndex.data_completeness_pct.desc().nullslast())
    elif sort == "relevance":
        stmt = stmt.order_by(
            SearchIndex.data_completeness_pct.desc().nullslast(), SearchIndex.vendor_name.asc()
        )
    else:
        stmt = stmt.order_by(SORT_OPTIONS[sort])

    rows = db.scalars(stmt.limit(limit).offset(offset)).all()
    return [_row_to_dict(row) for row in rows], int(total)


def _row_to_dict(row: SearchIndex) -> dict[str, Any]:
    return {
        "pump_model_id": str(row.pump_model_id),
        "pump_id": str(row.pump_id),
        "vendor_id": str(row.vendor_id),
        "label": row.label,
        "vendor_name": row.vendor_name,
        "pump_name": row.pump_name,
        "model_code": row.model_code,
        "summary": row.summary,
        "vendor_country": row.vendor_country,
        "country_of_origin": row.country_of_origin,
        "pump_type": row.pump_type.value if row.pump_type else None,
        "applicable_standard": (row.applicable_standard.value if row.applicable_standard else None),
        "service_application": row.service_application,
        "area_classification": row.area_classification,
        "seal_system_type": row.seal_system_type,
        "material_class": row.material_class,
        "certifications": row.certifications or [],
        "vendor_approval_status": (
            row.vendor_approval_status.value if row.vendor_approval_status else None
        ),
        "vendor_tier": row.vendor_tier,
        "fpso_experience": row.fpso_experience,
        "nace_compliant": row.nace_compliant,
        "rated_capacity_m3h": _decimal(row.rated_capacity_m3h),
        "rated_head_m": _decimal(row.rated_head_m),
        "npsh_required_m": _decimal(row.npsh_required_m),
        "hydraulic_efficiency_pct": _decimal(row.hydraulic_efficiency_pct),
        "rated_speed_rpm": row.rated_speed_rpm,
        "rated_power_kw": _decimal(row.rated_power_kw),
        "base_price_usd": _decimal(row.base_price_usd),
        "standard_lead_time_weeks": _decimal(row.standard_lead_time_weeks),
        "dry_weight_kg": _decimal(row.dry_weight_kg),
        "operating_weight_kg": _decimal(row.operating_weight_kg),
        "footprint_area_m2": _decimal(row.footprint_area_m2),
        "on_time_delivery_pct": _decimal(row.on_time_delivery_pct),
        "units_installed": row.units_installed,
        "mtbf_hours": row.mtbf_hours,
        "confidence_level": row.confidence_level.value if row.confidence_level else None,
        "verification_status": (row.verification_status.value if row.verification_status else None),
        "data_completeness_pct": _decimal(row.data_completeness_pct),
        "data_confidence_score": _decimal(row.data_confidence_score),
        "open_flag_count": row.open_flag_count,
        "is_shared_master": row.is_shared_master,
        "indexed_at": row.indexed_at.isoformat() if row.indexed_at else None,
    }


def _decimal(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def find_similar_pump_models(
    db: Session,
    pump_model_id: uuid.UUID,
    *,
    limit: int = 10,
    duty_tolerance_pct: Decimal = Decimal("25"),
) -> list[dict[str, Any]]:
    """Similar-pump matching on hydraulic distance, not text.

    Similarity is dominated by the duty point (capacity and head), then narrowed by
    pump type, then nudged by materials and area classification. Two pumps with the same
    name but a 10x duty gap are not alternatives; two differently named pumps hitting
    the same duty point are.
    """
    anchor = db.scalar(select(SearchIndex).where(SearchIndex.pump_model_id == pump_model_id))
    if anchor is None:
        return []
    if anchor.rated_capacity_m3h is None or anchor.rated_head_m is None:
        # Without a duty point there is nothing to be similar to; fall back to type.
        stmt = (
            select(SearchIndex)
            .where(
                SearchIndex.pump_model_id != pump_model_id,
                SearchIndex.pump_type == anchor.pump_type,
            )
            .order_by(SearchIndex.data_completeness_pct.desc().nullslast())
            .limit(limit)
        )
        return [dict(_row_to_dict(r), similarity=None) for r in db.scalars(stmt).all()]

    factor = duty_tolerance_pct / Decimal(100)
    capacity_low = anchor.rated_capacity_m3h * (1 - factor)
    capacity_high = anchor.rated_capacity_m3h * (1 + factor)
    head_low = anchor.rated_head_m * (1 - factor)
    head_high = anchor.rated_head_m * (1 + factor)

    # Normalised euclidean distance across the duty point; 0 is identical.
    distance = func.sqrt(
        func.power(
            (SearchIndex.rated_capacity_m3h - anchor.rated_capacity_m3h)
            / func.nullif(anchor.rated_capacity_m3h, 0),
            2,
        )
        + func.power(
            (SearchIndex.rated_head_m - anchor.rated_head_m) / func.nullif(anchor.rated_head_m, 0),
            2,
        )
    )

    stmt = (
        select(SearchIndex, distance.label("distance"))
        .where(
            SearchIndex.pump_model_id != pump_model_id,
            SearchIndex.rated_capacity_m3h.between(capacity_low, capacity_high),
            SearchIndex.rated_head_m.between(head_low, head_high),
        )
        .order_by(text("distance ASC"))
        .limit(limit * 3)
    )

    scored: list[dict[str, Any]] = []
    for row, raw_distance in db.execute(stmt).all():
        similarity = max(0.0, 1.0 - float(raw_distance or 0))
        # Type and material agreement are what make a candidate a real alternative.
        if row.pump_type == anchor.pump_type:
            similarity = min(1.0, similarity + 0.10)
        if row.material_class and row.material_class == anchor.material_class:
            similarity = min(1.0, similarity + 0.05)
        if row.area_classification == anchor.area_classification:
            similarity = min(1.0, similarity + 0.03)
        if row.applicable_standard != anchor.applicable_standard:
            similarity = max(0.0, similarity - 0.08)
        scored.append(dict(_row_to_dict(row), similarity=round(similarity, 4)))

    scored.sort(key=lambda r: r["similarity"] or 0, reverse=True)
    return scored[:limit]


def facet_counts(db: Session, filters: SearchFilters) -> dict[str, list[dict[str, Any]]]:
    """Counts per facet value for the filter sidebar, honouring the current filters."""
    facets: dict[str, list[dict[str, Any]]] = {}
    facet_columns = {
        "pump_type": SearchIndex.pump_type,
        "applicable_standard": SearchIndex.applicable_standard,
        "vendor_country": SearchIndex.vendor_country,
        "area_classification": SearchIndex.area_classification,
        "vendor_approval_status": SearchIndex.vendor_approval_status,
        "vendor_tier": SearchIndex.vendor_tier,
        "material_class": SearchIndex.material_class,
        "confidence_level": SearchIndex.confidence_level,
    }
    for name, column in facet_columns.items():
        stmt = select(column, func.count().label("count")).where(column.isnot(None))
        stmt = apply_filters(stmt, filters).group_by(column).order_by(func.count().desc())
        facets[name] = [
            {"value": value.value if hasattr(value, "value") else value, "count": int(count)}
            for value, count in db.execute(stmt.limit(30)).all()
        ]
    return facets
