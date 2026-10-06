"""Derive Pydantic models from the SQLAlchemy spec tables.

The six spec tables carry roughly 400 columns between them. Hand-writing read/create/
update schemas for all of them would guarantee drift the first time a field is added, so
they are generated from the model metadata instead. Column comments become field
descriptions, which means the OpenAPI document documents itself.

Identity, provenance and versioning columns are excluded from write schemas: those are
set by the platform, never by a client.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.sql.sqltypes import Enum as SAEnum

# Never client-writable.
SYSTEM_COLUMNS = frozenset(
    {
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
        "deleted_at",
        "version",
        "is_current",
        "superseded_at",
        "schema_version",
        "source_id",
        "ai_job_id",
        "created_by_user_id",
        "pump_model_id",
        "pump_id",
        "vendor_id",
        "normalized_name",
        "merged_into_vendor_id",
        "merged_into_pump_id",
        "merged_into_pump_model_id",
        "hashed_password",
        "hashed_key",
        "mfa_secret",
        "search_vector",
        "searchable_text",
    }
)


def python_type_for(column: Any) -> Any:
    """Map a SQLAlchemy column type onto the Python type Pydantic should validate."""
    col_type = column.type
    if isinstance(col_type, SAEnum):
        # Enum values are validated against the DB enum on write; expose as str so the
        # OpenAPI document lists them without coupling clients to Python enums.
        return str
    if isinstance(col_type, PGUUID):
        return uuid.UUID
    if isinstance(col_type, Boolean):
        return bool
    if isinstance(col_type, (Integer, BigInteger)):
        return int
    if isinstance(col_type, Numeric):
        return Decimal
    if isinstance(col_type, DateTime):
        return dt.datetime
    if isinstance(col_type, Date):
        return dt.date
    if isinstance(col_type, JSONB):
        return Any
    if isinstance(col_type, ARRAY):
        return list[str]
    if isinstance(col_type, (String, Text)):
        return str
    return Any


def _field_info(column: Any, optional: bool) -> Any:
    description = column.comment
    if isinstance(column.type, SAEnum) and column.type.enums:
        allowed = ", ".join(column.type.enums)
        description = f"{description + '. ' if description else ''}One of: {allowed}"
    max_length = getattr(column.type, "length", None)
    kwargs: dict[str, Any] = {"description": description}
    if max_length and python_type_for(column) is str:
        kwargs["max_length"] = max_length
    return Field(default=None if optional else ..., **kwargs)


def build_read_model(sa_model: type, name: str, exclude: set[str] | None = None) -> type[BaseModel]:
    """Every column, all optional - a read model must tolerate sparse data."""
    exclude = exclude or set()
    fields: dict[str, Any] = {}
    for column in sa_model.__table__.columns:
        if column.name in exclude:
            continue
        fields[column.name] = (
            python_type_for(column) | None,
            _field_info(column, optional=True),
        )
    return create_model(
        name, __config__=ConfigDict(from_attributes=True, use_enum_values=True), **fields
    )


def build_write_model(
    sa_model: type,
    name: str,
    *,
    exclude: set[str] | None = None,
    include_system: set[str] | None = None,
) -> type[BaseModel]:
    """Client-writable columns only, all optional so PATCH semantics come free."""
    exclude = (exclude or set()) | (SYSTEM_COLUMNS - (include_system or set()))
    fields: dict[str, Any] = {}
    for column in sa_model.__table__.columns:
        if column.name in exclude:
            continue
        fields[column.name] = (
            python_type_for(column) | None,
            _field_info(column, optional=True),
        )
    return create_model(
        name,
        __config__=ConfigDict(from_attributes=True, use_enum_values=True, extra="forbid"),
        **fields,
    )


def writable_field_names(sa_model: type, exclude: set[str] | None = None) -> list[str]:
    exclude = (exclude or set()) | SYSTEM_COLUMNS
    return [c.name for c in sa_model.__table__.columns if c.name not in exclude]
