"""Reusable column types."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import JSONB

# Money: 18 digits, 2 decimals - enough for EPC-scale package pricing.
Money = Numeric(18, 2)
# Engineering quantity: 18 digits, 6 decimals - covers efficiency, NPSHr, tolerances.
Quantity = Numeric(18, 6)
# Score: 0.000 - 100.000
Score = Numeric(6, 3)
# Probability / ratio: 0.0000 - 1.0000
Ratio = Numeric(5, 4)

Json = JSONB


def pg_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Native PostgreSQL enum built from a ``StrEnum`` using its *values*."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=True,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )
