"""Default inventory units seeded during organization bootstrap."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory.models import InventoryUnit

DEFAULT_INVENTORY_UNITS: tuple[tuple[str, str], ...] = (
    ("kg", "Kilogram"),
    ("mm", "Millimeter"),
)


async def seed_default_inventory_units(session: AsyncSession) -> dict[str, InventoryUnit]:
    """Insert kg and mm units if missing; return map keyed by code."""
    result: dict[str, InventoryUnit] = {}
    for code, name in DEFAULT_INVENTORY_UNITS:
        existing = await session.scalar(
            select(InventoryUnit).where(
                InventoryUnit.code == code,
                InventoryUnit.deleted_at.is_(None),
            )
        )
        if existing is not None:
            result[code] = existing
            continue
        row = InventoryUnit(code=code, name=name, is_active=True)
        session.add(row)
        await session.flush()
        result[code] = row
    return result
