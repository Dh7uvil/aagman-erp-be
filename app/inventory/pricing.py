"""Purchase price averages from stock-in and opening movements."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PurchasePriceStats:
    priced_count: int
    sum_kg: Decimal
    sum_kg_price: Decimal
    sum_price: Decimal


def compute_avg_price(stats: PurchasePriceStats | None) -> Decimal | None:
    if stats is None or stats.priced_count == 0:
        return None
    if stats.sum_kg > 0:
        return stats.sum_kg_price / stats.sum_kg
    return stats.sum_price / Decimal(stats.priced_count)


def valuation_unit_price(
    current_micron_price: Decimal | None,
    stats: PurchasePriceStats | None,
) -> Decimal | None:
    """Use avg purchase price when multiple priced receipts exist; else current micron price."""
    if stats is not None and stats.priced_count >= 2:
        return compute_avg_price(stats)
    return current_micron_price
