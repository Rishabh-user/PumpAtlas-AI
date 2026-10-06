"""SQLAlchemy models. Importing this package registers every table on ``Base.metadata``."""

from app.models.ai import (
    AiJob,
    AiSuggestion,
    ConfidenceScore,
    DataQualityFlag,
    DuplicateCandidate,
    ExtractedEntity,
    FieldProvenance,
)
from app.models.ai_settings import AiProviderConfig
from app.models.audit import AuditLog, RecordVersion
from app.models.base import Base
from app.models.comparison import (
    Comparison,
    ComparisonItem,
    RequirementProfile,
    SavedSearch,
    Tag,
    tagged_records,
)
from app.models.pump import Pump, PumpModel
from app.models.search import SearchIndex
from app.models.source import CrawlSchedule, Document, ImportBatch, Source
from app.models.specs import (
    AdministrativeSpec,
    CommercialSpec,
    DeliverySpec,
    DimensionalSpec,
    OperationalSpec,
    TechnicalSpec,
)
from app.models.tenant import Tenant, TenantPermission
from app.models.user import ApiKey, Role, User, user_roles

SPEC_MODELS = (
    TechnicalSpec,
    CommercialSpec,
    DimensionalSpec,
    DeliverySpec,
    OperationalSpec,
    AdministrativeSpec,
)

__all__ = [
    "AiProviderConfig",
    "AdministrativeSpec",
    "AiJob",
    "AiSuggestion",
    "ApiKey",
    "AuditLog",
    "Base",
    "CommercialSpec",
    "Comparison",
    "ComparisonItem",
    "ConfidenceScore",
    "CrawlSchedule",
    "DataQualityFlag",
    "DeliverySpec",
    "DimensionalSpec",
    "Document",
    "DuplicateCandidate",
    "ExtractedEntity",
    "FieldProvenance",
    "ImportBatch",
    "OperationalSpec",
    "Pump",
    "PumpModel",
    "RecordVersion",
    "RequirementProfile",
    "Role",
    "SPEC_MODELS",
    "SavedSearch",
    "SearchIndex",
    "Source",
    "Tag",
    "TechnicalSpec",
    "Tenant",
    "TenantPermission",
    "User",
    "tagged_records",
    "user_roles",
]
