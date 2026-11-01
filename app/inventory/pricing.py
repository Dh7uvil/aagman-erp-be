"""Purchase price averages from stock-in and opening movements."""

from __future__ import annotations

from collections.abc import Sequence
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


def merge_purchase_price_stats(
    stats_list: Sequence[PurchasePriceStats | None],
) -> PurchasePriceStats | None:
    priced_count = 0
    sum_kg = Decimal(0)
    sum_kg_price = Decimal(0)
    sum_price = Decimal(0)
    for stats in stats_list:
        if stats is None or stats.priced_count == 0:
            continue
        priced_count += stats.priced_count
        sum_kg += stats.sum_kg
        sum_kg_price += stats.sum_kg_price
        sum_price += stats.sum_price
    if priced_count == 0:
        return None
    return PurchasePriceStats(
        priced_count=priced_count,
        sum_kg=sum_kg,
        sum_kg_price=sum_kg_price,
        sum_price=sum_price,
    )


def valuation_unit_price(
    current_micron_price: Decimal | None,
    stats: PurchasePriceStats | None,
) -> Decimal | None:
    """Use avg purchase price when multiple priced receipts exist; else current micron price."""
    if stats is not None and stats.priced_count >= 2:
        return compute_avg_price(stats)
    return current_micron_price
