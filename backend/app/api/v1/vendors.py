"""Vendor intelligence endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.ai.parallel_search import vendor_intelligence_objective
from app.core.deps import CurrentPrincipal, DbSession, require
from app.models.ai import DataQualityFlag, FieldProvenance
from app.models.audit import RecordVersion
from app.models.enums import (
    AuditAction,
    ConfidenceLevel,
    ValueOrigin,
    VendorApprovalStatus,
)
from app.models.pump import Pump, PumpModel
from app.models.source import Source
from app.models.vendor import Vendor
from app.schemas.ai import DuplicateCandidateOut, MergeRequest
from app.schemas.common import Message, Page, ProvenanceEntry
from app.schemas.entities import (
    QualificationDecision,
    VendorContactIn,
    VendorContactOut,
    VendorCreate,
    VendorIn,
    VendorOut,
)
from app.services import (
    audit,
    dedupe,
    discovery,
    dispatch,
    indexing,
    provenance,
    records,
    vendor_discovery,
)
from app.services.promotion import normalize_company_name

router = APIRouter(prefix="/vendors", tags=["vendors"])


def _get_vendor(db: DbSession, vendor_id: uuid.UUID) -> Vendor:
    vendor = db.get(Vendor, vendor_id)
    if vendor is None or vendor.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")
    return vendor


@router.get("", response_model=Page[VendorOut], dependencies=[Depends(require("vendor", "read"))])
def list_vendors(
    principal: CurrentPrincipal,
    db: DbSession,
    q: str | None = Query(default=None, description="Name contains"),
    country: list[str] = Query(default_factory=list),
    approval_status: list[str] = Query(default_factory=list),
    vendor_tier: list[str] = Query(default_factory=list),
    fpso_experience: bool | None = None,
    include_shared_master: bool = True,
    tenant_scope: str | None = Query(
        default=None,
        description=(
            "Which catalogue to list: 'shared' for shared master data, 'all' for every "
            "catalogue the caller may see, or a tenant id. Defaults to 'shared' for a "
            "platform administrator and 'all' for a tenant user."
        ),
    ),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Vendors in one catalogue.

    The scope matters, and defaulting it to everything was wrong. A platform
    administrator sees every tenancy, so an unscoped list interleaved the shared-master
    catalogue with each client's own - 73 rows for 65 companies, with the eight that
    exist in both appearing twice. Nothing was duplicated; two separate catalogues were
    being shown as one list.

    So an administrator gets the shared-master catalogue by default, which is the one
    they curate, and can switch to a client's or to all of them. A tenant user is limited
    by row level security to their own plus shared master either way, which is the list
    they should see, so their default is unchanged.
    """
    stmt = select(Vendor).where(Vendor.deleted_at.is_(None), Vendor.merged_into_vendor_id.is_(None))

    scope = tenant_scope or ("shared" if principal.is_platform_admin else "all")
    if scope == "shared":
        stmt = stmt.where(Vendor.tenant_id.is_(None))
    elif scope != "all":
        try:
            scoped_tenant = uuid.UUID(scope)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"tenant_scope must be 'shared', 'all' or a tenant id, not {scope!r}",
            ) from exc
        stmt = stmt.where(Vendor.tenant_id == scoped_tenant)
    if q:
        stmt = stmt.where(Vendor.name.ilike(f"%{q}%"))
    if country:
        stmt = stmt.where(Vendor.country.in_([c.upper() for c in country]))
    if approval_status:
        stmt = stmt.where(Vendor.approval_status.in_(approval_status))
    if vendor_tier:
        stmt = stmt.where(Vendor.vendor_tier.in_(vendor_tier))
    if fpso_experience is not None:
        stmt = stmt.where(Vendor.fpso_offshore_experience.is_(fpso_experience))
    if not include_shared_master:
        stmt = stmt.where(Vendor.tenant_id.isnot(None))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Vendor.name).limit(limit).offset(offset)).all()

    # The same company can legitimately exist once per tenancy: a client's own supplier
    # record and the shared-master record are separate by design, and `merge_vendors`
    # refuses to cross that boundary. Without saying so, a platform administrator sees two
    # identical rows and reasonably reads it as a bug.
    #
    # One query for the whole page, not one per row - this database is remote.
    elsewhere = _tenancy_overlap(db, rows)
    items = []
    for row in rows:
        item = VendorOut.model_validate(row)
        item.also_in_other_tenancies = elsewhere.get(row.normalized_name, 0)
        items.append(item)
    return Page[VendorOut](items=items, total=int(total), limit=limit, offset=offset)


def _tenancy_overlap(db: DbSession, rows: list[Vendor]) -> dict[str, int]:
    """How many *other* tenancies hold each of these normalised names.

    The pairs come back and are grouped here rather than counted in SQL. The obvious
    `count(distinct coalesce(tenant_id, <sentinel>))` does not compile - PostgreSQL will
    not coalesce a uuid with a string - and a shared-master row has a null tenant, which
    `count(distinct)` would skip entirely, so the sentinel is not optional. Grouping in
    Python avoids both problems for a page of at most a few dozen names.

    Counted across every tenancy, which only a platform administrator's session can see.
    For a tenant user row level security limits the query to their own rows, so the answer
    is zero - which is the correct answer for them.
    """
    names = {row.normalized_name for row in rows if row.normalized_name}
    if not names:
        return {}
    pairs = db.execute(
        select(Vendor.normalized_name, Vendor.tenant_id)
        .where(
            Vendor.normalized_name.in_(names),
            Vendor.deleted_at.is_(None),
            Vendor.merged_into_vendor_id.is_(None),
        )
        .distinct()
    ).all()

    tenancies: dict[str, set[str]] = {}
    for name, tenant_id in pairs:
        tenancies.setdefault(name, set()).add(str(tenant_id) if tenant_id else "shared")
    # One tenancy holding it is not an overlap; two means one other.
    return {name: max(0, len(seen) - 1) for name, seen in tenancies.items()}


@router.post(
    "",
    response_model=VendorOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("vendor", "write"))],
)
def create_vendor(payload: VendorCreate, principal: CurrentPrincipal, db: DbSession) -> Vendor:
    if payload.is_shared_master and not principal.is_platform_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only platform admins may publish shared master data"
        )
    tenant_id = None if payload.is_shared_master else principal.require_tenant_id
    normalized = normalize_company_name(payload.name)

    clash = db.scalar(
        select(Vendor).where(
            Vendor.tenant_id == tenant_id,
            Vendor.normalized_name == normalized,
            Vendor.country == (payload.country or None),
            Vendor.deleted_at.is_(None),
        )
    )
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Vendor '{clash.name}' already exists with id {clash.id}. "
            "Update it, or use the duplicate review screen to merge.",
        )

    vendor = Vendor(
        tenant_id=tenant_id,
        name=payload.name,
        normalized_name=normalized,
        country=payload.country,
        hq_country=payload.country,
        website=payload.website,
        description=payload.description,
        is_shared_master=payload.is_shared_master,
        created_by_user_id=principal.user_id,
    )
    if payload.vendor_tier:
        vendor.vendor_tier = payload.vendor_tier
    db.add(vendor)
    db.flush()

    audit.record_audit(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        entity_type="vendors",
        entity_id=vendor.id,
        entity_label=vendor.name,
        summary="Vendor created manually",
    )
    audit.record_version(db, obj=vendor, operation="insert", principal=principal)
    dedupe.scan_vendor(db, vendor)
    db.commit()
    db.refresh(vendor)
    return vendor


@router.get(
    "/{vendor_id}", response_model=VendorOut, dependencies=[Depends(require("vendor", "read"))]
)
def get_vendor(vendor_id: uuid.UUID, db: DbSession) -> Vendor:
    return _get_vendor(db, vendor_id)


@router.get("/{vendor_id}/profile", dependencies=[Depends(require("vendor", "read"))])
def vendor_profile(vendor_id: uuid.UUID, db: DbSession) -> dict:
    """Everything the vendor page renders: identity, models, flags, provenance."""
    vendor = _get_vendor(db, vendor_id)

    pump_rows = db.execute(
        select(Pump, func.count(PumpModel.id))
        .outerjoin(PumpModel, (PumpModel.pump_id == Pump.id) & PumpModel.deleted_at.is_(None))
        .where(Pump.vendor_id == vendor.id, Pump.deleted_at.is_(None))
        .group_by(Pump.id)
        .order_by(Pump.name)
    ).all()

    open_flags = db.scalars(
        select(DataQualityFlag)
        .where(
            DataQualityFlag.entity_id == vendor.id,
            DataQualityFlag.is_resolved.is_(False),
        )
        .order_by(DataQualityFlag.severity.desc())
        .limit(50)
    ).all()

    contacts = vendor_discovery.contact_rows(db, vendor.id)

    return {
        "vendor": records.to_jsonable(
            {c.name: getattr(vendor, c.name) for c in vendor.__table__.columns}
        ),
        "contacts": [records.to_jsonable(row) for row in contacts],
        "product_lines": [
            {
                "pump_id": str(pump.id),
                "name": pump.name,
                "pump_type": pump.pump_type.value if pump.pump_type else None,
                "applicable_standard": (
                    pump.applicable_standard.value if pump.applicable_standard else None
                ),
                "service_application": pump.service_application,
                "model_count": int(model_count),
            }
            for pump, model_count in pump_rows
        ],
        "open_flags": [
            {
                "id": str(flag.id),
                "field_name": flag.field_name,
                "flag_type": flag.flag_type.value,
                "severity": flag.severity.value,
                "message": flag.message,
            }
            for flag in open_flags
        ],
        "provenance_summary": records.provenance_summary(db, [("vendors", vendor.id)]),
    }


@router.patch(
    "/{vendor_id}", response_model=VendorOut, dependencies=[Depends(require("vendor", "write"))]
)
def update_vendor(
    vendor_id: uuid.UUID, payload: VendorIn, principal: CurrentPrincipal, db: DbSession
) -> Vendor:
    """Manual edit. Every changed field is written through provenance as human-origin."""
    vendor = _get_vendor(db, vendor_id)
    if vendor.tenant_id is None and not principal.is_platform_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Shared master records are edited by platform admins only"
        )

    before = audit.snapshot(vendor)
    values = payload.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields supplied")

    context = provenance.ProvenanceContext(
        origin=ValueOrigin.MANUAL,
        confidence_level=vendor.confidence_level,
        changed_by_user_id=principal.user_id,
        tenant_id=vendor.tenant_id,
    )
    report = provenance.apply_fields(db, vendor, values, context)
    if "name" in report["applied"]:
        vendor.normalized_name = normalize_company_name(vendor.name)

    audit.record_audit(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        entity_type="vendors",
        entity_id=vendor.id,
        entity_label=vendor.name,
        summary=f"Updated {len(report['applied'])} field(s)",
        changes=audit.diff(before, audit.snapshot(vendor)),
    )
    audit.record_version(db, obj=vendor, operation="update", before=before, principal=principal)
    indexing.reindex_vendor(db, vendor.id)
    db.commit()
    db.refresh(vendor)
    return vendor


@router.post(
    "/{vendor_id}/qualification",
    dependencies=[Depends(require("vendor", "write"))],
)
def set_qualification(
    vendor_id: uuid.UUID,
    payload: QualificationDecision,
    principal: CurrentPrincipal,
    db: DbSession,
) -> dict:
    """Record this organisation's decision about whether a supplier may be used.

    `approval_status` was readable everywhere - a badge on the profile, a filter on the
    list, a column in search - and settable nowhere: no screen wrote it, so every record
    sat at `pending_qualification` unless the extractor had written a supplier's own
    claim into it. A field a buyer is meant to rely on that nobody can set is not a
    qualification process.

    What this writes that a generic field edit does not:

    * `approved_by_user_id`, so the decision has an owner. Cleared when the status is
      not an approval, because "not approved by" is not a thing to record.
    * `approval_expiry`, so an approval can lapse rather than stand forever.
    * The reason, as the evidence behind the status - the same gate every other stored
      value passes through. A decision nobody can account for is the thing this platform
      exists to prevent.
    """
    vendor = _get_vendor(db, vendor_id)
    if vendor.tenant_id is None and not principal.is_platform_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Shared master records are qualified by platform admins only",
        )

    before = audit.snapshot(vendor)
    approving = payload.approval_status in (
        VendorApprovalStatus.APPROVED,
        VendorApprovalStatus.CONDITIONALLY_APPROVED,
    )

    context = provenance.ProvenanceContext(
        origin=ValueOrigin.MANUAL,
        confidence_level=ConfidenceLevel.VERIFIED,
        changed_by_user_id=principal.user_id,
        tenant_id=vendor.tenant_id,
    )
    values: dict[str, Any] = {"approval_status": payload.approval_status.value}
    if payload.approval_expiry is not None:
        values["approval_expiry"] = payload.approval_expiry
    report = provenance.apply_fields(
        db, vendor, values, context, evidence={name: payload.note for name in values}
    )

    vendor.approved_by_user_id = principal.user_id if approving else None
    if not approving:
        vendor.approval_expiry = None

    audit.record_audit(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        entity_type="vendors",
        entity_id=vendor.id,
        entity_label=vendor.name,
        summary=f"Qualification set to {payload.approval_status.value}",
        changes={"approval_status": payload.approval_status.value, "note": payload.note},
    )
    audit.record_version(
        db,
        obj=vendor,
        operation="update",
        before=before,
        principal=principal,
        change_reason=payload.note,
    )
    indexing.reindex_vendor(db, vendor.id)
    db.commit()
    db.refresh(vendor)
    return {
        "vendor_id": str(vendor.id),
        # From the validated request rather than the attribute: between the assignment
        # and the refresh the column holds whatever was put there, which is a plain
        # string, and `.value` on it raises.
        "approval_status": payload.approval_status.value,
        "approval_expiry": vendor.approval_expiry,
        "approved_by_user_id": (
            str(vendor.approved_by_user_id) if vendor.approved_by_user_id else None
        ),
        "applied": report["applied"],
    }


@router.delete(
    "/{vendor_id}", response_model=Message, dependencies=[Depends(require("vendor", "delete"))]
)
def delete_vendor(vendor_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> Message:
    """Soft delete. Sources, documents and audit history are retained."""
    vendor = _get_vendor(db, vendor_id)
    vendor.deleted_at = func.now()
    audit.record_audit(
        db,
        action=AuditAction.DELETE,
        principal=principal,
        entity_type="vendors",
        entity_id=vendor.id,
        entity_label=vendor.name,
        summary="Vendor soft deleted",
    )
    indexing.reindex_vendor(db, vendor.id)
    db.commit()
    return Message(detail=f"Vendor {vendor.name} deleted")


@router.post(
    "/{vendor_id}/enrich",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require("ingestion", "write"))],
)
def enrich_vendor(
    vendor_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DbSession,
    max_results: int = Query(default=6, ge=1, le=25),
    auto_apply: bool = Query(
        default=True,
        description=(
            "Write confident values onto this vendor as each page is read. The candidate "
            "resolves by name to this record, so there is no ambiguity about where the "
            "values land; turn it off to review them in the AI queue first."
        ),
    ),
) -> dict:
    """Fill in this vendor's record from the web.

    A vendor discovered while storing a pump model is a name and nothing else:
    `resolve_vendor` inserts the row so the model has a manufacturer, and no page has
    been read about the company itself. That is why a profile shows "—" against annual
    revenue, employees, certifications and manufacturing countries while the record is
    marked AI extracted - the AI read a product page, not a company.

    This asks the questions a procurement file needs answered - company profile and
    locations, API and ISO certifications, offshore and FPSO references, annual report -
    reads each page it finds, and applies what it can quote. Every value still carries a
    verbatim quote and a source, exactly as the review queue would write it.
    """
    vendor = _get_vendor(db, vendor_id)

    objective, queries = vendor_intelligence_objective(vendor.name)
    batch = discovery.start_run(
        db,
        vendor_discovery.KIND,
        tenant_id=vendor.tenant_id,
        query=vendor.name,
        country=vendor.hq_country,
        objective=objective,
        queries=queries,
        max_results=max_results,
        user_id=principal.user_id,
        target_vendor_id=vendor.id,
        auto_store=auto_apply,
        transport="celery" if dispatch.broker_available() else "in_process",
    )
    audit.record_audit(
        db,
        action=AuditAction.IMPORT,
        principal=principal,
        entity_type="vendors",
        entity_id=vendor.id,
        entity_label=vendor.name,
        summary="Vendor enrichment started from the web",
        context={"objective": objective, "queries": queries, "auto_apply": auto_apply},
    )
    db.commit()

    from app.workers.tasks import discovery_task

    outcome = dispatch.dispatch(
        celery_task=discovery_task,
        celery_args=(
            vendor_discovery.KIND.slug,
            str(batch.id),
            str(vendor.tenant_id) if vendor.tenant_id else None,
            str(principal.user_id) if principal.user_id else None,
        ),
        fallback=_enrichment_runner(),
        fallback_kwargs={"batch_id": batch.id, "user_id": principal.user_id},
        tenant_id=vendor.tenant_id,
        name="vendor-enrichment",
    )
    discovery.record_transport(db, batch.id, outcome["transport"], outcome["task_id"])
    db.commit()

    return {
        "run_id": str(batch.id),
        "vendor_id": str(vendor.id),
        "queries": queries,
        "transport": outcome.get("transport"),
        # So the screen can watch it with the panel that already knows how.
        "watch": f"/vendor-discovery/{batch.id}",
        "auto_apply": auto_apply,
    }


def _enrichment_runner():
    """Bind the vendor kind for the in-process fallback, which passes only ids."""

    def run(db, *, batch_id, user_id):
        return discovery.run_discovery(db, vendor_discovery.KIND, batch_id, user_id)

    return run


#: Columns a version diff should not report as a change: identity, bookkeeping, and the
#: timestamps that move on every write. A reader wants "it gained a headquarters", not
#: "updated_at changed".
VERSION_NOISE_FIELDS = frozenset(
    {
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
        "created_by_user_id",
        "normalized_name",
        "schema_version",
    }
)


@router.get(
    "/{vendor_id}/provenance",
    response_model=list[ProvenanceEntry],
    dependencies=[Depends(require("vendor", "read"))],
)
def vendor_provenance(
    vendor_id: uuid.UUID,
    db: DbSession,
    field_name: str | None = Query(default=None),
) -> list:
    """Field-by-field lineage: source, evidence quote, model and confidence."""
    _get_vendor(db, vendor_id)
    return provenance.field_history(db, "vendors", vendor_id, field_name)


@router.get(
    "/{vendor_id}/contact-details",
    dependencies=[Depends(require("vendor", "read"))],
)
def vendor_contact_details(vendor_id: uuid.UUID, db: DbSession) -> dict:
    """Contact details found on the captured pages that are *not* recorded yet.

    A capture records what the company's own site states about itself, each contact
    carrying the page it was read from. What this endpoint returns is the remainder -
    mostly details from somebody else's domain, which are never recorded automatically.

    That distinction is the whole point. A supplier's page routinely lists its
    distributors - one Amarinth page carried a partner's address and a Brazilian number -
    and writing those onto Amarinth would put another company's switchboard in this
    company's file. A person decides those, and the audit log captures the decision.

    The pages are the ones that actually produced this record: its primary source plus
    every source cited by its field provenance. Anything already held as a contact is
    dropped, so nothing appears twice.
    """
    vendor = _get_vendor(db, vendor_id)
    vendor_domain = vendor_discovery.domain_of(vendor.website)

    # `vendor_contacts` is not soft-deleted: a removed contact is gone, and offering it
    # again is the right behaviour.
    held = vendor_discovery.contact_rows(db, vendor.id)
    held_emails = {(row["email"] or "").lower() for row in held if row["email"]}
    held_phones = {
        vendor_discovery.phone_key(row["phone"]) for row in held if row["phone"]
    }

    source_ids = set(
        db.scalars(
            select(FieldProvenance.source_id).where(
                FieldProvenance.entity_type == "vendors",
                FieldProvenance.entity_id == vendor.id,
                FieldProvenance.source_id.isnot(None),
            )
        ).all()
    )
    if vendor.primary_source_id:
        source_ids.add(vendor.primary_source_id)
    if not source_ids:
        return {"emails": [], "phones": []}

    emails: dict[str, dict] = {}
    phones: dict[str, dict] = {}
    for source in db.scalars(select(Source).where(Source.id.in_(source_ids))).all():
        captured = (source.source_metadata or {}).get("content") or {}
        seen_on = {
            "source_id": str(source.id),
            "url": source.source_url,
            "title": source.title,
            "captured_at": source.captured_at,
        }
        page_domain = vendor_discovery.domain_of(source.source_url)
        seen_on["same_domain"] = bool(
            page_domain and vendor_domain and page_domain == vendor_domain
        )
        for address in captured.get("emails") or []:
            if address.lower() in held_emails:
                continue
            emails.setdefault(address.lower(), {"value": address, "seen_on": seen_on})
        for number in captured.get("phones") or []:
            # Keyed on the digits alone: one page listed "+65 9385 2894" and
            # "+65 9385-2894", which are one switchboard written twice. The first
            # spelling seen is the one shown.
            digits = vendor_discovery.phone_key(number)
            if digits in held_phones:
                continue
            phones.setdefault(
                digits, {"value": number.strip(), "seen_on": seen_on}
            )

    return {"emails": list(emails.values()), "phones": list(phones.values())}


@router.get(
    "/{vendor_id}/versions",
    dependencies=[Depends(require("vendor", "read"))],
)
def vendor_versions(
    vendor_id: uuid.UUID,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    """What this record looked like after each change, newest first.

    The diff is what a reader actually wants - "this run added the headquarters and the
    product families" - so the changed field names and their old and new values come back
    flattened, with the bookkeeping columns dropped. The full snapshot stays in the row
    for a rollback; it is not worth sending to a screen.
    """
    _get_vendor(db, vendor_id)
    rows = db.scalars(
        select(RecordVersion)
        .where(
            RecordVersion.entity_type == "vendors",
            RecordVersion.entity_id == vendor_id,
        )
        .order_by(RecordVersion.version.desc())
        .limit(limit)
    ).all()

    out: list[dict] = []
    for row in rows:
        changes = [
            {"field": field, "from": change.get("from"), "to": change.get("to")}
            for field, change in sorted((row.diff or {}).items())
            if field not in VERSION_NOISE_FIELDS
        ]
        out.append(
            {
                "version": row.version,
                "operation": row.operation,
                "created_at": row.created_at,
                "change_reason": row.change_reason,
                "changed_by_user_id": row.changed_by_user_id,
                "ai_job_id": row.ai_job_id,
                "changes": changes,
                "change_count": len(changes),
            }
        )
    return out


@router.get(
    "/{vendor_id}/duplicates",
    dependencies=[Depends(require("vendor", "read"))],
)
def vendor_duplicates(vendor_id: uuid.UUID, db: DbSession) -> dict:
    """Re-run duplicate detection for one vendor.

    Two lists, because they call for different actions. ``candidates`` are duplicates
    within this vendor's own tenancy, which `POST /vendors/merge` can resolve.
    ``also_in_other_tenancies`` is the same company recorded elsewhere on the platform -
    information for a platform administrator, not a task, because merging across a tenant
    boundary is refused by design.
    """
    vendor = _get_vendor(db, vendor_id)
    dedupe.scan_vendor(db, vendor)
    db.commit()

    # The same company recorded in another tenancy is not a task: `merge_vendors` refuses
    # to cross that boundary, because one client's supplier record and the shared-master
    # record for the same company are separate by design. Reported separately so a
    # platform administrator can see the overlap without being handed a duplicate they
    # cannot resolve.
    elsewhere = [
        {
            "id": str(other.id),
            "name": other.name,
            "tenant_id": str(other.tenant_id) if other.tenant_id else None,
            "is_shared_master": other.tenant_id is None,
            "score": round(score, 3),
        }
        for other, score, _ in dedupe.find_vendor_duplicates(db, vendor, same_tenant_only=False)
        if other.tenant_id != vendor.tenant_id
    ]

    from app.models.ai import DuplicateCandidate

    rows = db.scalars(
        select(DuplicateCandidate)
        .where(
            DuplicateCandidate.entity_type == "vendors",
            (DuplicateCandidate.entity_id_a == vendor.id)
            | (DuplicateCandidate.entity_id_b == vendor.id),
            DuplicateCandidate.status == "open",
        )
        .order_by(DuplicateCandidate.similarity_score.desc())
    ).all()

    out = []
    for row in rows:
        other_id = row.entity_id_b if row.entity_id_a == vendor.id else row.entity_id_a
        other = db.get(Vendor, other_id)
        out.append(
            DuplicateCandidateOut(
                id=row.id,
                entity_type=row.entity_type,
                entity_id_a=row.entity_id_a,
                entity_id_b=row.entity_id_b,
                similarity_score=float(row.similarity_score),
                match_signals=row.match_signals,
                detection_method=row.detection_method,
                status=row.status,
                label_a=vendor.name
                if row.entity_id_a == vendor.id
                else (other.name if other else None),
                label_b=other.name if other and row.entity_id_b == other_id else vendor.name,
                created_at=row.created_at,
            )
        )
    return {"candidates": out, "also_in_other_tenancies": elsewhere}


@router.post("/merge", dependencies=[Depends(require("vendor", "approve"))])
def merge_vendors(payload: MergeRequest, principal: CurrentPrincipal, db: DbSession) -> dict:
    """Merge a duplicate into a surviving vendor. Nothing is deleted."""
    try:
        result = dedupe.merge_vendors(
            db,
            keep_id=payload.keep_id,
            merge_id=payload.merge_id,
            principal=principal,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    indexing.reindex_vendor(db, payload.keep_id)
    db.commit()
    return result


@router.get(
    "/{vendor_id}/contacts",
    response_model=list[VendorContactOut],
    dependencies=[Depends(require("vendor", "read"))],
)
def list_contacts(vendor_id: uuid.UUID, db: DbSession) -> list:
    _get_vendor(db, vendor_id)
    return vendor_discovery.contact_rows(db, vendor_id)


@router.post(
    "/{vendor_id}/contacts",
    response_model=VendorContactOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("vendor", "write"))],
)
def _one_contact(db: DbSession, vendor_id: uuid.UUID, contact_id: uuid.UUID) -> dict:
    for row in vendor_discovery.contact_rows(db, vendor_id):
        if row["id"] == contact_id:
            return row
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")


def create_contact(
    vendor_id: uuid.UUID,
    payload: VendorContactIn,
    principal: CurrentPrincipal,
    db: DbSession,
) -> dict:
    vendor = _get_vendor(db, vendor_id)
    contact_id = vendor_discovery.insert_contact(
        db,
        vendor_id=vendor.id,
        tenant_id=vendor.tenant_id,
        origin=ValueOrigin.MANUAL.value,
        **payload.model_dump(exclude_none=True),
    )
    audit.record_audit(
        db,
        action=AuditAction.CREATE,
        principal=principal,
        entity_type="vendor_contacts",
        entity_label=f"{vendor.name}: {payload.full_name or payload.company_name}",
        summary="Vendor contact added",
    )
    db.commit()
    # Read back through the real columns rather than refreshing the entity: an ORM
    # refresh asks for every mapped column, including any this database has not been
    # migrated for yet.
    return _one_contact(db, vendor.id, contact_id)


@router.post("/{vendor_id}/summarise", dependencies=[Depends(require("vendor", "write"))])
def summarise_vendor(vendor_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> dict:
    """Queue a Gemma vendor briefing. Returns the job id to poll."""
    vendor = _get_vendor(db, vendor_id)
    from app.workers.tasks import summarise_vendor_task

    task = summarise_vendor_task.delay(
        str(vendor.id),
        str(vendor.tenant_id) if vendor.tenant_id else None,
        str(principal.user_id) if principal.user_id else None,
    )
    return {
        "queued": True,
        "task_id": task.id,
        "vendor_id": str(vendor.id),
        "detail": "Vendor summary is being generated from facts already in the database",
    }
