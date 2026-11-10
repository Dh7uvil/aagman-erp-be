"""Shared query resolution for movement day/range reports."""

from datetime import date

from app.core.exceptions import ValidationError


def resolve_movement_report_range(
    *,
    report_date: date | None,
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, date]:
    if start_date is not None or end_date is not None:
        if start_date is None or end_date is None:
            raise ValidationError("Both start_date and end_date are required for a date range")
        if start_date > end_date:
            raise ValidationError("start_date must not be after end_date")
        return start_date, end_date
    if report_date is not None:
        return report_date, report_date
    raise ValidationError("Provide date or both start_date and end_date")
