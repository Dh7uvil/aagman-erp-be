"""Unit tests for purchase price averaging."""

from decimal import Decimal

from app.inventory.pricing import (
    PurchasePriceStats,
    compute_avg_price,
    merge_purchase_price_stats,
    valuation_unit_price,
)


def test_compute_avg_price_kg_weighted() -> None:
    stats = PurchasePriceStats(
        priced_count=2,
        sum_kg=Decimal("150"),
        sum_kg_price=Decimal("10050"),
        sum_price=Decimal("175.5"),
    )
    assert compute_avg_price(stats) == Decimal("67")


def test_compute_avg_price_simple_when_no_kg() -> None:
    stats = PurchasePriceStats(
        priced_count=2,
        sum_kg=Decimal("0"),
        sum_kg_price=Decimal("0"),
        sum_price=Decimal("187.5"),
    )
    assert compute_avg_price(stats) == Decimal("93.75")


def test_valuation_uses_avg_when_multiple_receipts() -> None:
    stats = PurchasePriceStats(
        priced_count=2,
        sum_kg=Decimal("100"),
        sum_kg_price=Decimal("5000"),
        sum_price=Decimal("100"),
    )
    assert valuation_unit_price(Decimal("99"), stats) == Decimal("50")


def test_merge_purchase_price_stats_kg_weighted() -> None:
    a = PurchasePriceStats(
        priced_count=1,
        sum_kg=Decimal("100"),
        sum_kg_price=Decimal("6000"),
        sum_price=Decimal("60"),
    )
    b = PurchasePriceStats(
        priced_count=1,
        sum_kg=Decimal("50"),
        sum_kg_price=Decimal("4050"),
        sum_price=Decimal("81"),
    )
    merged = merge_purchase_price_stats([a, b])
    assert merged is not None
    assert compute_avg_price(merged) == Decimal("67")


def test_valuation_uses_current_when_single_receipt() -> None:
    stats = PurchasePriceStats(
        priced_count=1,
        sum_kg=Decimal("100"),
        sum_kg_price=Decimal("5000"),
        sum_price=Decimal("50"),
    )
    assert valuation_unit_price(Decimal("99"), stats) == Decimal("99")
