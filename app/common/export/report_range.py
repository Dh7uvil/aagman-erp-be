"""Date range resolution for movement report exports."""

from __future__ import annotations

from datetime import date

from app.common.dependencies.export_scope import ExportScope, is_full_module_export
from app.inventory.report_range import resolve_movement_report_range


def resolve_export_report_range(
    *,
    export_scope: ExportScope,
    report_date: date | None,
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, date]:
    if is_full_module_export(export_scope):
        return date(1970, 1, 1), date.today()
    return resolve_movement_report_range(
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
    )
