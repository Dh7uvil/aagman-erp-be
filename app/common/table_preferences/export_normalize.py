"""Merge and validation for export column preferences."""

from __future__ import annotations

from dataclasses import dataclass

from app.common.table_preferences.catalog import TableCatalogEntry
from app.common.table_preferences.normalize import _as_string_list, _dedupe, complete_order
from app.core.exceptions import ValidationError


@dataclass(frozen=True, slots=True)
class NormalizedExportPreference:
    export_visible_columns: list[str]
    export_column_order: list[str]


def merge_export_stored(
    entry: TableCatalogEntry,
    *,
    export_visible_columns: object,
    export_column_order: object,
    permissions: frozenset[str],
    fallback_visible_columns: list[str] | None = None,
    fallback_column_order: list[str] | None = None,
) -> NormalizedExportPreference:
    allowed = entry.exportable_keys(permissions)
    allowed_set = set(allowed)
    raw_visible = export_visible_columns if isinstance(export_visible_columns, list) else []
    raw_order = export_column_order if isinstance(export_column_order, list) else []
    visible = [
        key
        for key in _dedupe([item for item in raw_visible if isinstance(item, str)])
        if key in allowed_set
    ]
    order = complete_order(
        [item for item in raw_order if isinstance(item, str)],
        allowed,
    )
    if not visible and fallback_visible_columns:
        visible = [
            key for key in _dedupe(fallback_visible_columns) if key in allowed_set
        ]
    if not order and fallback_column_order:
        order = complete_order(
            [item for item in fallback_column_order if isinstance(item, str)],
            allowed,
        )
    if not visible:
        return NormalizedExportPreference(
            export_visible_columns=entry.default_export_visible(permissions),
            export_column_order=entry.default_export_order(permissions),
        )
    return NormalizedExportPreference(
        export_visible_columns=visible,
        export_column_order=complete_order(order, allowed),
    )


def validate_export_update(
    entry: TableCatalogEntry,
    *,
    export_visible_columns: list[str],
    export_column_order: list[str],
    permissions: frozenset[str],
) -> NormalizedExportPreference:
    allowed = entry.exportable_keys(permissions)
    allowed_set = set(allowed)
    max_len = max(len(allowed), 1)

    visible = _as_string_list(export_visible_columns, field_name="export_visible_columns")
    order = _as_string_list(export_column_order, field_name="export_column_order")

    if len(visible) > max_len or len(order) > max_len:
        raise ValidationError(
            "Too many export column keys",
            details={"max_columns": max_len},
        )
    if len(visible) != len(set(visible)):
        raise ValidationError(
            "export_visible_columns must not contain duplicates",
            details={"field": "export_visible_columns"},
        )
    if len(order) != len(set(order)):
        raise ValidationError(
            "export_column_order must not contain duplicates",
            details={"field": "export_column_order"},
        )

    unknown = sorted({key for key in (*visible, *order) if key not in allowed_set})
    if unknown:
        raise ValidationError(
            "Export column keys are not allowed for this table",
            details={"unknown_columns": unknown},
        )
    if not visible:
        raise ValidationError(
            "At least one export column must be visible",
            details={"field": "export_visible_columns"},
        )

    return NormalizedExportPreference(
        export_visible_columns=visible,
        export_column_order=complete_order(order, allowed),
    )
