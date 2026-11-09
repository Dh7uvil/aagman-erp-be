"""Resolve export columns from catalog + user preferences."""

from __future__ import annotations

from dataclasses import dataclass

from app.common.table_preferences.catalog import TableCatalogEntry
from app.common.table_preferences.export_normalize import (
    merge_export_stored,
    validate_export_update,
)


@dataclass(frozen=True, slots=True)
class ResolvedExportColumns:
    visible_keys: list[str]
    order: list[str]


def resolve_export_column_keys(
    entry: TableCatalogEntry,
    *,
    export_visible_columns: object,
    export_column_order: object,
    permissions: frozenset[str],
    strict: bool = False,
) -> ResolvedExportColumns:
    allowed = entry.exportable_keys(permissions)
    if not allowed:
        return ResolvedExportColumns(visible_keys=[], order=[])
    if strict:
        merged = validate_export_update(
            entry,
            export_visible_columns=(
                export_visible_columns if isinstance(export_visible_columns, list) else []
            ),
            export_column_order=export_column_order
            if isinstance(export_column_order, list)
            else [],
            permissions=permissions,
        )
    else:
        merged = merge_export_stored(
            entry,
            export_visible_columns=export_visible_columns,
            export_column_order=export_column_order,
            permissions=permissions,
        )
    return ResolvedExportColumns(
        visible_keys=merged.export_visible_columns,
        order=merged.export_column_order,
    )


def ordered_visible_keys(resolved: ResolvedExportColumns) -> list[str]:
    visible = set(resolved.visible_keys)
    return [key for key in resolved.order if key in visible]
