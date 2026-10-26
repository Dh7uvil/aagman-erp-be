"""Top-level API router."""

from fastapi import APIRouter

from app.common.table_preferences.router import router as table_preferences_router
from app.core.config import get_settings
from app.identity.router import router as identity_router
from app.inventory.router import router as inventory_router

settings = get_settings()

api_router = APIRouter(prefix=settings.api_v1_prefix)

api_router.include_router(identity_router)
api_router.include_router(inventory_router)
api_router.include_router(table_preferences_router)
