"""Shared export column types."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

AggregateKind = Literal["sum"]


@dataclass(frozen=True, slots=True)
class ExportColumn:
    key: str
    header: str
    value_fn: Callable[[Any], object]
    aggregate: AggregateKind | None = None


def format_export_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Decimal):
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def sum_numeric_values(values: list[object]) -> Decimal | None:
    total = Decimal("0")
    found = False
    for value in values:
        if value is None:
            continue
        if isinstance(value, Decimal):
            total += value
            found = True
        elif isinstance(value, (int, float)):
            total += Decimal(str(value))
            found = True
    return total if found else None
