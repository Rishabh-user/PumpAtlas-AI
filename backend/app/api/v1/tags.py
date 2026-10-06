"""Tags: watchlists, project codes and risk markers."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, insert, select

from app.core.deps import CurrentPrincipal, DbSession, require
from app.models.comparison import Tag, tagged_records
from app.models.enums import AuditAction
from app.schemas.common import Message
from app.schemas.comparison import TagAssignment, TagIn, TagOut
from app.services import audit

router = APIRouter(prefix="/tags", tags=["tags"])

TAGGABLE_TYPES = {"vendors", "pumps", "pump_models"}


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80]


@router.get("", response_model=list[TagOut], dependencies=[Depends(require("search", "read"))])
def list_tags(db: DbSession, category: str | None = None) -> list:
    stmt = select(Tag)
    if category:
        stmt = stmt.where(Tag.category == category)
    return list(db.scalars(stmt.order_by(Tag.name)).all())


@router.post(
    "",
    response_model=TagOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("vendor", "write"))],
)
def create_tag(payload: TagIn, principal: CurrentPrincipal, db: DbSession) -> Tag:
    tenant_id = principal.require_tenant_id
    slug = payload.slug or _slugify(payload.name)
    if db.scalar(select(Tag).where(Tag.tenant_id == tenant_id, Tag.slug == slug)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Tag '{slug}' already exists")

    tag = Tag(
        tenant_id=tenant_id,
        slug=slug,
        name=payload.name,
        description=payload.description,
        color=payload.color,
        category=payload.category,
        created_by_user_id=principal.user_id,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.post(
    "/{tag_id}/assign", response_model=Message, dependencies=[Depends(require("vendor", "write"))]
)
def assign_tag(
    tag_id: uuid.UUID,
    payload: TagAssignment,
    principal: CurrentPrincipal,
    db: DbSession,
) -> Message:
    if payload.entity_type not in TAGGABLE_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"entity_type must be one of: {', '.join(sorted(TAGGABLE_TYPES))}",
        )
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")

    already = db.scalar(
        select(func.count())
        .select_from(tagged_records)
        .where(
            tagged_records.c.tag_id == tag_id,
            tagged_records.c.entity_type == payload.entity_type,
            tagged_records.c.entity_id == payload.entity_id,
        )
    )
    if already:
        return Message(detail="Already tagged")

    db.execute(
        insert(tagged_records).values(
            tag_id=tag_id,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            tenant_id=principal.tenant_id,
            tagged_by_user_id=principal.user_id,
            created_at=datetime.now(UTC),
        )
    )
    tag.usage_count += 1
    audit.record_audit(
        db,
        action=AuditAction.UPDATE,
        principal=principal,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        entity_label=tag.name,
        summary=f"Tagged '{tag.name}'",
    )
    db.commit()
    return Message(detail=f"Tagged with '{tag.name}'")


@router.delete(
    "/{tag_id}/assign", response_model=Message, dependencies=[Depends(require("vendor", "write"))]
)
def unassign_tag(
    tag_id: uuid.UUID,
    db: DbSession,
    entity_type: str = Query(description="vendors | pumps | pump_models"),
    entity_id: uuid.UUID = Query(),
) -> Message:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    result = db.execute(
        delete(tagged_records).where(
            tagged_records.c.tag_id == tag_id,
            tagged_records.c.entity_type == entity_type,
            tagged_records.c.entity_id == entity_id,
        )
    )
    if result.rowcount:
        tag.usage_count = max(0, tag.usage_count - 1)
    db.commit()
    return Message(detail="Tag removed" if result.rowcount else "Tag was not assigned")


@router.get(
    "/for/{entity_type}/{entity_id}",
    response_model=list[TagOut],
    dependencies=[Depends(require("search", "read"))],
)
def tags_for_entity(entity_type: str, entity_id: uuid.UUID, db: DbSession) -> list:
    """Tags attached to one record."""
    return list(
        db.scalars(
            select(Tag)
            .join(tagged_records, tagged_records.c.tag_id == Tag.id)
            .where(
                tagged_records.c.entity_type == entity_type,
                tagged_records.c.entity_id == entity_id,
            )
        ).all()
    )
