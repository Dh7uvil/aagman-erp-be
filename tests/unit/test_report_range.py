"""Unit tests for movement report date query resolution."""

from datetime import date

import pytest

from app.core.exceptions import ValidationError
from app.inventory.report_range import resolve_movement_report_range


def test_resolve_single_date() -> None:
    d = date(2026, 3, 1)
    start, end = resolve_movement_report_range(report_date=d, start_date=None, end_date=None)
    assert start == d
    assert end == d


def test_resolve_explicit_range() -> None:
    start, end = resolve_movement_report_range(
        report_date=None,
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 5),
    )
    assert start == date(2026, 3, 1)
    assert end == date(2026, 3, 5)


def test_resolve_rejects_partial_range() -> None:
    with pytest.raises(ValidationError):
        resolve_movement_report_range(
            report_date=None,
            start_date=date(2026, 3, 1),
            end_date=None,
        )


def test_resolve_rejects_inverted_range() -> None:
    with pytest.raises(ValidationError):
        resolve_movement_report_range(
            report_date=None,
            start_date=date(2026, 3, 5),
            end_date=date(2026, 3, 1),
        )
