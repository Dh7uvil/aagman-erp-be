"""Materials list export column extractors."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.common.export.build_columns import build_export_columns
from app.inventory.schemas import MaterialResponse


def _attr(name: str) -> Callable[[MaterialResponse], object]:
    def getter(row: MaterialResponse) -> object:
        return getattr(row, name)

    return getter


_MATERIAL_EXTRACTORS: dict[str, Callable[[Any], object]] = {
    "company": lambda row: row.company_name,
    "product": lambda row: row.product_name,
    "micron": lambda row: row.micron_name,
    "size": lambda row: row.size_label or row.size,
    "rolls": lambda row: row.rolls_on_hand,
    "total_kg": lambda row: row.total_kg,
    "price_per_unit": _attr("price_per_unit"),
    "avg_price_per_unit": _attr("avg_price_per_unit"),
    "active": _attr("is_active"),
}


def material_export_columns(
    keys: list[str],
    *,
    permissions: frozenset[str],
) -> list:
    return build_export_columns(
        "inventory.materials",
        keys,
        _MATERIAL_EXTRACTORS,
        permissions=permissions,
    )
