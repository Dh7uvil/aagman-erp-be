"""HTTP responses for file exports."""

from __future__ import annotations

from fastapi import Response

from app.common.export.types import ExportColumn
from app.common.export.writers import write_csv, write_xlsx
from app.common.utils.files import MIME_CSV, MIME_XLSX


def export_file_response(
    *,
    format: str,
    filename_stem: str,
    rows: list[object],
    columns: list[ExportColumn],
) -> Response:
    if format == "xlsx":
        body = write_xlsx(rows, columns)
        return Response(
            content=body,
            media_type=MIME_XLSX,
            headers={
                "Content-Disposition": f'attachment; filename="{filename_stem}.xlsx"',
            },
        )
    csv_body = write_csv(rows, columns)
    return Response(
        content=csv_body,
        media_type=MIME_CSV,
        headers={
            "Content-Disposition": f'attachment; filename="{filename_stem}.csv"',
        },
    )
