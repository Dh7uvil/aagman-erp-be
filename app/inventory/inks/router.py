"""Ink HTTP routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response

from app.common.dependencies.auth import CurrentUser, CurrentUserDependency
from app.common.dependencies.export_scope import ExportScopeQuery, is_full_module_export
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import ReferenceListAccess, require_permission
from app.common.export.report_range import resolve_export_report_range
from app.common.export.service import compute_list_column_totals, export_catalog_table
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.services.entity_history import EntityHistoryEntry
from app.common.table_preferences.dependencies import TablePreferenceServiceDependency
from app.inventory.catalog import (
    INK_COLOR_CREATE,
    INK_COLOR_DELETE,
    INK_COLOR_HISTORY,
    INK_COLOR_READ,
    INK_COLOR_UPDATE,
    INK_CREATE,
    INK_DELETE,
    INK_HISTORY,
    INK_READ,
    INK_UPDATE,
    INKS_REPORT_READ,
)
from app.inventory.inks.dependencies import InkServiceDependency
from app.inventory.inks.schemas import (
    INK_FILE_SLOTS,
    InkBrandCreate,
    InkBrandFilter,
    InkBrandResponse,
    InkBrandUpdate,
    InkColorCreate,
    InkColorFilter,
    InkColorResponse,
    InkColorUpdate,
    InkColorUsageResponse,
    InkDayReportRow,
    InkLineListItem,
    InkLineResponse,
    InkSheetCreate,
    InkSheetFilter,
    InkSheetResponse,
    InkSheetUpdate,
    InkStockOutCreate,
)
from app.inventory.report_range import resolve_movement_report_range
from app.inventory.schemas import DrumLineHistoryEntry, DrumLineHistorySummary

ink_colors_router = APIRouter(prefix="/ink-colors", tags=["Ink Colors"])
ink_brands_router = APIRouter(prefix="/ink-brands", tags=["Ink Brands"])
inks_router = APIRouter(prefix="/inks", tags=["Inks"])
ink_movements_router = APIRouter(prefix="/ink-movements", tags=["Ink Movements"])
ink_lines_router = APIRouter(prefix="/ink-lines", tags=["Ink Lines"])


@ink_colors_router.get("", response_model=ApiResponse[list[InkColorResponse]])
async def list_ink_colors(
    page: PaginationDependency,
    current_user: ReferenceListAccess,
    service: InkServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[InkColorFilter, Depends()],
    include_column_totals: Annotated[bool, Query()] = False,
) -> ApiResponse[list[InkColorResponse]]:
    rows, total = await service.list_colors(
        page=page,
        common_filter=filters,
        is_active=filters.is_active,
    )
    column_totals = None
    if include_column_totals:
        export_rows = await service.list_colors_for_export(
            common_filter=filters,
            is_active=filters.is_active,
        )
        column_totals = await compute_list_column_totals(
            preference_service,
            user_id=current_user.user_id,
            table_key="inventory.ink_colors",
            permissions=current_user.permissions,
            rows=export_rows,
        )
    return paginated_response(rows, params=page, total=total, column_totals=column_totals)


@ink_colors_router.get("/export", response_class=Response)
async def export_ink_colors(
    current_user: ReferenceListAccess,
    service: InkServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[InkColorFilter, Depends()],
    export_scope: ExportScopeQuery,
    format: Annotated[str, Query(pattern="^(csv|xlsx)$")] = "csv",
) -> Response:
    scope_filters = InkColorFilter() if is_full_module_export(export_scope) else filters
    rows = await service.list_colors_for_export(
        common_filter=scope_filters,
        is_active=scope_filters.is_active,
    )
    return await export_catalog_table(
        preference_service,
        user_id=current_user.user_id,
        table_key="inventory.ink_colors",
        permissions=current_user.permissions,
        filename_stem="ink-colors",
        format=format,
        rows=rows,
    )


@ink_colors_router.post(
    "",
    response_model=ApiResponse[InkColorResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_ink_color(
    payload: InkColorCreate,
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_COLOR_CREATE))],
) -> ApiResponse[InkColorResponse]:
    return ApiResponse(
        data=await service.create_color(payload, actor_user_id=current_user.user_id),
        message="Ink color created successfully",
    )


@ink_colors_router.get("/{color_id}/usage/export", response_class=Response)
async def export_ink_color_usage(
    color_id: UUID,
    current_user: CurrentUserDependency,
    service: InkServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_COLOR_READ))],
    export_scope: ExportScopeQuery,
    format: Annotated[str, Query(pattern="^(csv|xlsx)$")] = "csv",
) -> Response:
    rows = await service.color_usage_for_export(color_id, permissions=current_user.permissions)
    return await export_catalog_table(
        preference_service,
        user_id=current_user.user_id,
        table_key="inventory.ink_color_usage",
        permissions=current_user.permissions,
        filename_stem="ink-color-usage",
        format=format,
        rows=rows,
    )


@ink_colors_router.get("/{color_id}", response_model=ApiResponse[InkColorResponse])
async def get_ink_color(
    color_id: UUID,
    service: InkServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_COLOR_READ))],
) -> ApiResponse[InkColorResponse]:
    return ApiResponse(data=await service.get_color(color_id))


@ink_colors_router.get("/{color_id}/usage", response_model=ApiResponse[InkColorUsageResponse])
async def get_ink_color_usage(
    color_id: UUID,
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_COLOR_READ))],
) -> ApiResponse[InkColorUsageResponse]:
    return ApiResponse(
        data=await service.color_usage(color_id, permissions=current_user.permissions),
    )


@ink_colors_router.patch("/{color_id}", response_model=ApiResponse[InkColorResponse])
async def update_ink_color(
    color_id: UUID,
    payload: InkColorUpdate,
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_COLOR_UPDATE))],
) -> ApiResponse[InkColorResponse]:
    return ApiResponse(
        data=await service.update_color(color_id, payload, actor_user_id=current_user.user_id),
        message="Ink color updated successfully",
    )


@ink_colors_router.get("/{color_id}/history", response_model=ApiResponse[list[EntityHistoryEntry]])
async def ink_color_history(
    color_id: UUID,
    page: PaginationDependency,
    service: InkServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_COLOR_HISTORY))],
) -> ApiResponse[list[EntityHistoryEntry]]:
    rows, total = await service.color_history(color_id, page=page)
    return paginated_response(rows, params=page, total=total)


@ink_colors_router.delete("/{color_id}", response_model=ApiResponse[InkColorResponse])
async def delete_ink_color(
    color_id: UUID,
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_COLOR_DELETE))],
) -> ApiResponse[InkColorResponse]:
    return ApiResponse(
        data=await service.delete_color(color_id, actor_user_id=current_user.user_id),
        message="Ink color deleted successfully",
    )


@ink_brands_router.get("", response_model=ApiResponse[list[InkBrandResponse]])
async def list_ink_brands(
    page: PaginationDependency,
    current_user: ReferenceListAccess,
    service: InkServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[InkBrandFilter, Depends()],
    include_column_totals: Annotated[bool, Query()] = False,
) -> ApiResponse[list[InkBrandResponse]]:
    rows, total = await service.list_brands(
        page=page,
        common_filter=filters,
        is_active=filters.is_active,
    )
    column_totals = None
    if include_column_totals:
        export_rows = await service.list_brands_for_export(
            common_filter=filters,
            is_active=filters.is_active,
        )
        column_totals = await compute_list_column_totals(
            preference_service,
            user_id=current_user.user_id,
            table_key="inventory.ink_brands",
            permissions=current_user.permissions,
            rows=export_rows,
        )
    return paginated_response(rows, params=page, total=total, column_totals=column_totals)


@ink_brands_router.get("/export", response_class=Response)
async def export_ink_brands(
    current_user: ReferenceListAccess,
    service: InkServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[InkBrandFilter, Depends()],
    export_scope: ExportScopeQuery,
    format: Annotated[str, Query(pattern="^(csv|xlsx)$")] = "csv",
) -> Response:
    scope_filters = InkBrandFilter() if is_full_module_export(export_scope) else filters
    rows = await service.list_brands_for_export(
        common_filter=scope_filters,
        is_active=scope_filters.is_active,
    )
    return await export_catalog_table(
        preference_service,
        user_id=current_user.user_id,
        table_key="inventory.ink_brands",
        permissions=current_user.permissions,
        filename_stem="ink-brands",
        format=format,
        rows=rows,
    )


@ink_brands_router.post(
    "",
    response_model=ApiResponse[InkBrandResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_ink_brand(
    payload: InkBrandCreate,
    service: InkServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_CREATE))],
) -> ApiResponse[InkBrandResponse]:
    return ApiResponse(
        data=await service.create_brand(payload), message="Ink brand created successfully"
    )


@ink_brands_router.get("/{brand_id}", response_model=ApiResponse[InkBrandResponse])
async def get_ink_brand(
    brand_id: UUID,
    service: InkServiceDependency,
    _: ReferenceListAccess,
) -> ApiResponse[InkBrandResponse]:
    return ApiResponse(data=await service.get_brand(brand_id))


@ink_brands_router.patch("/{brand_id}", response_model=ApiResponse[InkBrandResponse])
async def update_ink_brand(
    brand_id: UUID,
    payload: InkBrandUpdate,
    service: InkServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_UPDATE))],
) -> ApiResponse[InkBrandResponse]:
    return ApiResponse(
        data=await service.update_brand(brand_id, payload), message="Ink brand updated successfully"
    )


@ink_brands_router.delete("/{brand_id}", response_model=ApiResponse[InkBrandResponse])
async def delete_ink_brand(
    brand_id: UUID,
    service: InkServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_DELETE))],
) -> ApiResponse[InkBrandResponse]:
    return ApiResponse(
        data=await service.delete_brand(brand_id), message="Ink brand deleted successfully"
    )


@inks_router.get("", response_model=ApiResponse[list[InkLineListItem]])
async def list_inks(
    page: PaginationDependency,
    service: InkServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[InkSheetFilter, Depends()],
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_READ))],
    include_column_totals: Annotated[bool, Query()] = False,
) -> ApiResponse[list[InkLineListItem]]:
    rows, total = await service.list_line_items(
        page=page,
        common_filter=filters,
        company_id=filters.company_id,
        permissions=current_user.permissions,
    )
    column_totals = None
    if include_column_totals:
        export_rows = await service.list_line_items_for_export(
            common_filter=filters,
            company_id=filters.company_id,
            permissions=current_user.permissions,
        )
        column_totals = await compute_list_column_totals(
            preference_service,
            user_id=current_user.user_id,
            table_key="inventory.inks",
            permissions=current_user.permissions,
            rows=export_rows,
        )
    return paginated_response(rows, params=page, total=total, column_totals=column_totals)


@inks_router.get("/export", response_class=Response)
async def export_inks(
    current_user: CurrentUserDependency,
    service: InkServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[InkSheetFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(INK_READ))],
    export_scope: ExportScopeQuery,
    format: Annotated[str, Query(pattern="^(csv|xlsx)$")] = "csv",
) -> Response:
    scope_filters = InkSheetFilter() if is_full_module_export(export_scope) else filters
    rows = await service.list_line_items_for_export(
        common_filter=scope_filters,
        company_id=scope_filters.company_id,
        permissions=current_user.permissions,
    )
    return await export_catalog_table(
        preference_service,
        user_id=current_user.user_id,
        table_key="inventory.inks",
        permissions=current_user.permissions,
        filename_stem="inks",
        format=format,
        rows=rows,
    )


@inks_router.post(
    "",
    response_model=ApiResponse[InkSheetResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_ink_sheet(
    payload: InkSheetCreate,
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_CREATE))],
) -> ApiResponse[InkSheetResponse]:
    row = await service.create_sheet(
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Ink sheet created successfully")


@inks_router.get("/{sheet_id}", response_model=ApiResponse[InkSheetResponse])
async def get_ink_sheet(
    sheet_id: UUID,
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_READ))],
) -> ApiResponse[InkSheetResponse]:
    return ApiResponse(data=await service.get_sheet(sheet_id, permissions=current_user.permissions))


@inks_router.patch("/{sheet_id}", response_model=ApiResponse[InkSheetResponse])
async def update_ink_sheet(
    sheet_id: UUID,
    payload: InkSheetUpdate,
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_UPDATE))],
) -> ApiResponse[InkSheetResponse]:
    row = await service.update_sheet(
        sheet_id,
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Ink sheet updated successfully")


@inks_router.delete("/{sheet_id}", response_model=ApiResponse[InkSheetResponse])
async def delete_ink_sheet(
    sheet_id: UUID,
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_DELETE))],
) -> ApiResponse[InkSheetResponse]:
    return ApiResponse(
        data=await service.delete_sheet(sheet_id, actor_user_id=current_user.user_id),
        message="Ink sheet deleted successfully",
    )


@inks_router.get("/{sheet_id}/history", response_model=ApiResponse[list[EntityHistoryEntry]])
async def ink_sheet_history(
    sheet_id: UUID,
    page: PaginationDependency,
    service: InkServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_HISTORY))],
) -> ApiResponse[list[EntityHistoryEntry]]:
    rows, total = await service.sheet_history(sheet_id, page=page)
    return paginated_response(rows, params=page, total=total)


@inks_router.get(
    "/{sheet_id}/history-attachments/{audit_log_id}",
    response_class=Response,
)
async def download_ink_history_attachment(
    sheet_id: UUID,
    audit_log_id: UUID,
    current_user: CurrentUserDependency,
    service: InkServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_HISTORY))],
) -> Response:
    body, content_type = await service.read_history_attachment(
        sheet_id,
        audit_log_id,
        permissions=current_user.permissions,
    )
    return Response(content=body, media_type=content_type)


@inks_router.post("/{sheet_id}/stock-out", response_model=ApiResponse[InkLineResponse])
async def ink_stock_out(
    sheet_id: UUID,
    payload: InkStockOutCreate,
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_UPDATE))],
) -> ApiResponse[InkLineResponse]:
    row = await service.stock_out(
        sheet_id,
        payload,
        actor_user_id=current_user.user_id,
    )
    return ApiResponse(data=row, message="Stock out recorded successfully")


@inks_router.post("/{sheet_id}/files/{slot}", response_model=ApiResponse[InkSheetResponse])
async def upload_ink_file(
    sheet_id: UUID,
    slot: str,
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
    file: UploadFile = File(...),
) -> ApiResponse[InkSheetResponse]:
    if slot not in INK_FILE_SLOTS:
        from app.core.exceptions import ValidationError

        raise ValidationError("Invalid file slot")
    row = await service.upload_file(
        sheet_id,
        slot,
        file,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="File uploaded successfully")


@inks_router.get("/{sheet_id}/files/{slot}", response_class=Response)
async def download_ink_file(
    sheet_id: UUID,
    slot: str,
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
) -> Response:
    content, content_type = await service.read_file(
        sheet_id,
        slot,
        permissions=current_user.permissions,
    )
    return Response(content=content, media_type=content_type)


@inks_router.delete("/{sheet_id}/files/{slot}", response_model=ApiResponse[InkSheetResponse])
async def delete_ink_file(
    sheet_id: UUID,
    slot: str,
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
) -> ApiResponse[InkSheetResponse]:
    row = await service.delete_file(
        sheet_id,
        slot,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="File removed successfully")


@ink_lines_router.get("/{line_id}/history", response_model=ApiResponse[list[DrumLineHistoryEntry]])
async def ink_line_history(
    line_id: UUID,
    page: PaginationDependency,
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_HISTORY))],
) -> ApiResponse[list[DrumLineHistoryEntry]]:
    rows, total = await service.line_history(
        line_id,
        page=page,
        permissions=current_user.permissions,
    )
    return paginated_response(rows, params=page, total=total)


@ink_lines_router.get(
    "/{line_id}/history-summary",
    response_model=ApiResponse[DrumLineHistorySummary],
)
async def ink_line_history_summary(
    line_id: UUID,
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_HISTORY))],
) -> ApiResponse[DrumLineHistorySummary]:
    return ApiResponse(
        data=await service.line_history_summary(line_id, permissions=current_user.permissions),
    )


@ink_movements_router.get("/report", response_model=ApiResponse[list[InkDayReportRow]])
async def ink_movement_day_report(
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
    preference_service: TablePreferenceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INKS_REPORT_READ))],
    report_date: Annotated[date | None, Query(alias="date")] = None,
    start_date: Annotated[date | None, Query(alias="start_date")] = None,
    end_date: Annotated[date | None, Query(alias="end_date")] = None,
    include_column_totals: Annotated[bool, Query()] = False,
) -> ApiResponse[list[InkDayReportRow]]:
    start, end = resolve_movement_report_range(
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
    )
    rows = await service.day_report(
        start_date=start,
        end_date=end,
        permissions=current_user.permissions,
    )
    meta: dict[str, object] = {}
    if include_column_totals:
        meta["column_totals"] = await compute_list_column_totals(
            preference_service,
            user_id=current_user.user_id,
            table_key="inventory.inks_report",
            permissions=current_user.permissions,
            rows=rows,
        )
    return ApiResponse(data=rows, meta=meta)


@ink_movements_router.get("/report/export", response_class=Response)
async def export_ink_day_report(
    current_user: CurrentUserDependency,
    service: InkServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INKS_REPORT_READ))],
    export_scope: ExportScopeQuery,
    format: Annotated[str, Query(pattern="^(csv|xlsx)$")] = "csv",
    report_date: Annotated[date | None, Query(alias="date")] = None,
    start_date: Annotated[date | None, Query(alias="start_date")] = None,
    end_date: Annotated[date | None, Query(alias="end_date")] = None,
) -> Response:
    start, end = resolve_export_report_range(
        export_scope=export_scope,
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
    )
    rows = await service.inks_day_report_for_export(
        start_date=start,
        end_date=end,
        permissions=current_user.permissions,
    )
    return await export_catalog_table(
        preference_service,
        user_id=current_user.user_id,
        table_key="inventory.inks_report",
        permissions=current_user.permissions,
        filename_stem="inks-report",
        format=format,
        rows=rows,
    )
