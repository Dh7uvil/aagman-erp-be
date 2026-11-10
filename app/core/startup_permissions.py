"""Permission catalog sync on application startup."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text

from app.cli.export_permissions_catalog import export_catalog
from app.core.config import Settings
from app.db.session import async_session_factory, transaction
from app.identity.catalog import ensure_superadmin

logger = logging.getLogger(__name__)

_ADVISORY_LOCK_KEY = 7_401_001


async def sync_permissions_on_startup(settings: Settings) -> None:
    if not settings.auto_sync_permissions or settings.env == "testing":
        return
    try:
        async with async_session_factory() as session, transaction(session):
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
            await ensure_superadmin(session)
        if settings.env == "development":
            repo_root = Path(__file__).resolve().parents[2]
            export_catalog(repo_root / "docs" / "permissions-catalog.json")
    except Exception as exc:
        logger.warning("Permission sync on startup skipped: %s", exc)
