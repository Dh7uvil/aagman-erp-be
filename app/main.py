"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.error_handlers import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import engine
from app.health import router as health_router
from app.router import api_router

OPENAPI_TAGS: list[dict[str, str]] = [
    {"name": "Health", "description": "Process liveness and dependency readiness probes."},
    {"name": "Auth", "description": "Authentication and session management."},
    {"name": "Users", "description": "User management and role assignment."},
    {"name": "Roles", "description": "Role management and permission assignment."},
    {"name": "Permissions", "description": "Permission catalog and matrix."},
    {"name": "Organization", "description": "Singleton organization settings and logo."},
    {"name": "Branches", "description": "Operating locations."},
    {"name": "Departments", "description": "Departments within branches."},
    {"name": "Warehouses", "description": "Warehouse master data."},
    {"name": "Companies", "description": "Company master data."},
    {"name": "Audit Logs", "description": "Append-only audit trail."},
    {"name": "Inventory", "description": "Units, materials, and stock movements."},
    {"name": "Inventory Units", "description": "Units of measure."},
    {"name": "Material Categories", "description": "Material category master."},
    {"name": "Materials", "description": "Material subcategories and on-hand balances."},
    {"name": "Material Movements", "description": "Daily stock in and out."},
]


@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.env in {"staging", "production"} and not settings.cors_origins:
        msg = "CORS origins must be configured in staging and production"
        raise RuntimeError(msg)
    configure_logging(settings.log_level)

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        openapi_tags=OPENAPI_TAGS,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin).rstrip("/") for origin in settings.cors_origins],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestContextMiddleware)

    register_error_handlers(application)
    application.include_router(health_router)
    application.include_router(api_router)
    return application


app = create_app()
