"""Shared response envelopes and pagination."""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(description="Total rows matching the query, ignoring pagination")
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class PaginationParams(BaseModel):
    limit: int = Field(default=25, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class Message(BaseModel):
    detail: str


class BulkResult(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)


class ProvenanceEntry(ORMModel):
    """Why a field holds the value it holds."""

    field_name: str
    value_text: str | None = None
    previous_value_text: str | None = None
    value_origin: str
    confidence_level: str
    confidence_score: float | None = None
    source_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    ai_job_id: uuid.UUID | None = None
    model_used: str | None = None
    evidence_quote: str | None = None
    evidence_locator: str | None = None
    original_value: str | None = None
    original_unit: str | None = None
    changed_by_user_id: uuid.UUID | None = None
    is_current: bool
    created_at: Any = None


class FieldFlag(ORMModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    field_name: str | None = None
    flag_type: str
    severity: str
    message: str
    detected_value: str | None = None
    expected_range: str | None = None
    suggested_fix: str | None = None
    detected_by: str
    is_resolved: bool
    created_at: Any = None


class ScorecardOut(BaseModel):
    kind: str
    score: float
    grade: str
    fields_evaluated: int
    fields_missing: int
    disqualified: bool = False
    disqualification_reason: str | None = None
    breakdown: dict[str, Any] = Field(default_factory=dict)
