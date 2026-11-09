"""CSV and XLSX export writers."""

from __future__ import annotations

import csv
import io
from decimal import Decimal

from openpyxl import Workbook

from app.common.export.types import ExportColumn, format_export_cell, sum_numeric_values


def build_rows(
    data_rows: list[object],
    columns: list[ExportColumn],
) -> tuple[list[list[str]], list[str]]:
    """Return body rows and optional totals row (empty strings where not aggregated)."""

    body: list[list[str]] = []
    aggregate_buffers: dict[str, list[object]] = {
        column.key: [] for column in columns if column.aggregate == "sum"
    }

    for row in data_rows:
        line: list[str] = []
        for column in columns:
            raw = column.value_fn(row)
            if column.key in aggregate_buffers:
                aggregate_buffers[column.key].append(raw)
            line.append(format_export_cell(raw))
        body.append(line)

    totals_line: list[str] = []
    if aggregate_buffers:
        label_placed = False
        for column in columns:
            if column.aggregate == "sum":
                total = sum_numeric_values(aggregate_buffers[column.key])
                totals_line.append(format_export_cell(total))
            elif not label_placed:
                totals_line.append("Total")
                label_placed = True
            else:
                totals_line.append("")
    return body, totals_line


def write_csv(
    data_rows: list[object],
    columns: list[ExportColumn],
    *,
    include_totals: bool = True,
) -> str:
    body, totals_line = build_rows(data_rows, columns)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([column.header for column in columns])
    writer.writerows(body)
    if include_totals and totals_line:
        writer.writerow(totals_line)
    return buffer.getvalue()


def write_xlsx(
    data_rows: list[object],
    columns: list[ExportColumn],
    *,
    include_totals: bool = True,
) -> bytes:
    body, totals_line = build_rows(data_rows, columns)
    workbook = Workbook()
    sheet = workbook.active
    if sheet is None:
        sheet = workbook.create_sheet("Export")
    sheet.append([column.header for column in columns])
    for line in body:
        sheet.append(line)
    if include_totals and totals_line:
        sheet.append(totals_line)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def totals_from_rows(
    data_rows: list[object],
    columns: list[ExportColumn],
) -> dict[str, str]:
    """Compute aggregate footer values for selected export columns."""

    result: dict[str, str] = {}
    for column in columns:
        if column.aggregate != "sum":
            continue
        values = [column.value_fn(row) for row in data_rows]
        total = sum_numeric_values(values)
        if total is not None:
            result[column.key] = format_export_cell(total)
    return result


def decimal_dict_totals(totals: dict[str, Decimal | None]) -> dict[str, str]:
    return {key: format_export_cell(value) for key, value in totals.items() if value is not None}
