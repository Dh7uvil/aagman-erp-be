"""Generic helpers to build export files from table preferences."""

from __future__ import annotations

from uuid import UUID

from fastapi import Response

from app.common.export.build_columns import build_export_columns
from app.common.export.extractors import get_table_extractors
from app.common.export.http import export_file_response
from app.core.exceptions import ResourceNotFoundError, ValidationError


async def export_catalog_table(
    preference_service,
    *,
    user_id: UUID,
    table_key: str,
    permissions: frozenset[str],
    filename_stem: str,
    format: str,
    rows: list[object],
) -> Response:
    column_keys, _saved_format = await preference_service.get_export_columns(
        user_id,
        table_key,
        permissions=permissions,
    )
    export_format = format if format in {"csv", "xlsx"} else "csv"
    return build_table_export(
        table_key=table_key,
        rows=rows,
        column_keys=column_keys,
        permissions=permissions,
        format=export_format,
        filename_stem=filename_stem,
    )


def build_table_export(
    *,
    table_key: str,
    rows: list[object],
    column_keys: list[str],
    permissions: frozenset[str],
    format: str,
    filename_stem: str,
) -> Response:
    extractors = get_table_extractors(table_key)
    if extractors is None:
        raise ResourceNotFoundError(f"Export is not configured for {table_key}")
    columns = build_export_columns(table_key, column_keys, extractors, permissions=permissions)
    if not columns:
        raise ValidationError("No export columns available")
    return export_file_response(
        format=format,
        filename_stem=filename_stem,
        rows=rows,
        columns=columns,
    )


def column_totals_from_rows(
    table_key: str,
    rows: list[object],
    column_keys: list[str],
    permissions: frozenset[str],
) -> dict[str, str]:
    from app.common.export.writers import totals_from_rows

    extractors = get_table_extractors(table_key)
    if extractors is None:
        return {}
    columns = build_export_columns(table_key, column_keys, extractors, permissions=permissions)
    export_keys = set(column_keys)
    filtered = [column for column in columns if column.key in export_keys]
    from app.common.table_preferences.catalog import get_table_catalog

    entry = get_table_catalog(table_key)
    if entry is None:
        return {}
    aggregate_keys = set(entry.aggregate_keys(permissions))
    totals = totals_from_rows(rows, [column for column in filtered if column.key in aggregate_keys])
    return totals


async def compute_list_column_totals(
    preference_service,
    *,
    user_id: UUID,
    table_key: str,
    permissions: frozenset[str],
    rows: list[object],
) -> dict[str, str]:
    prefs = await preference_service.get(user_id, table_key, permissions=permissions)
    return column_totals_from_rows(
        table_key,
        rows,
        column_keys=prefs.visible_columns,
        permissions=permissions,
    )
