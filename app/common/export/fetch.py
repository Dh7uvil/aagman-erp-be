"""Export fetch limits."""

from __future__ import annotations

from app.common.export.limits import MAX_EXPORT_ROWS
from app.common.schemas.pagination import PageParams
from app.core.exceptions import ValidationError


def export_page() -> PageParams:
    return PageParams(page=1, page_size=MAX_EXPORT_ROWS)


def assert_export_total(total: int) -> None:
    if total > MAX_EXPORT_ROWS:
        raise ValidationError(
            f"Too many rows to export (max {MAX_EXPORT_ROWS})",
            details={"total": total, "max_export_rows": MAX_EXPORT_ROWS},
        )
