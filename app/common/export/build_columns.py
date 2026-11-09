"""Build ExportColumn list from catalog + extractors."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.common.export.catalog_headers import export_header_for_key
from app.common.export.types import ExportColumn
from app.common.table_preferences.catalog import get_table_catalog


def build_export_columns(
    table_key: str,
    keys: list[str],
    extractors: dict[str, Callable[[Any], object]],
    *,
    permissions: frozenset[str],
) -> list[ExportColumn]:
    entry = get_table_catalog(table_key)
    if entry is None:
        return []
    columns: list[ExportColumn] = []
    for key in keys:
        if key not in extractors:
            continue
        spec = entry.column_by_key(key)
        columns.append(
            ExportColumn(
                key=key,
                header=export_header_for_key(key),
                value_fn=extractors[key],
                aggregate=spec.aggregate if spec else None,
            )
        )
    allowed = set(entry.exportable_keys(permissions))
    return [column for column in columns if column.key in allowed]
