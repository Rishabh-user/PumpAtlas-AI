"""Aggregate the v1 API surface."""

from fastapi import APIRouter

from app.api.v1 import (
    admin_database,
    ai_review,
    ai_settings_routes,
    audit,
    auth,
    chat_routes,
    comparisons,
    discovery_routes,
    ingest,
    pumps,
    quality,
    search,
    system,
    tags,
    tenants,
    vendors,
)

api_router = APIRouter()

# Order matters only where paths could shadow one another; each module keeps its
# static routes ahead of its parameterised ones.
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(tenants.router)
api_router.include_router(vendors.router)
api_router.include_router(discovery_routes.vendor_router)
api_router.include_router(discovery_routes.pump_router)
api_router.include_router(pumps.router)
api_router.include_router(search.router)
api_router.include_router(ingest.router)
api_router.include_router(ai_review.router)
api_router.include_router(quality.router)
api_router.include_router(comparisons.router)
api_router.include_router(audit.router)
api_router.include_router(tags.router)
api_router.include_router(admin_database.router)
api_router.include_router(ai_settings_routes.router)
api_router.include_router(chat_routes.router)
