"""Derived cylinder list/export field values."""

from __future__ import annotations

from decimal import Decimal


def total_cylinder_cost(
    cylinder_cost: Decimal | None,
    cylinder_count: int | None,
) -> Decimal | None:
    if cylinder_cost is None or cylinder_count is None:
        return None
    return (cylinder_cost * Decimal(cylinder_count)).quantize(Decimal("0.01"))
