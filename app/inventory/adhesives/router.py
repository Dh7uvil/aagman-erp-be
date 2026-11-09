"""Adhesive HTTP routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
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
from app.inventory.adhesives.dependencies import AdhesiveServiceDependency
from app.inventory.adhesives.schemas import (
    AdhesiveBrandCreate,
    AdhesiveBrandFilter,
    AdhesiveBrandResponse,
    AdhesiveBrandUpdate,
    AdhesiveCodeCreate,
    AdhesiveCodeFilter,
    AdhesiveCodeResponse,
    AdhesiveCodeUpdate,
    AdhesiveCodeUsageResponse,
    AdhesiveDayReportRow,
    AdhesiveLineListItem,
    AdhesiveLineResponse,
    AdhesiveSheetCreate,
    AdhesiveSheetFilter,
    AdhesiveSheetResponse,
    AdhesiveSheetUpdate,
    AdhesiveStockOutCreate,
)
from app.inventory.catalog import (
    ADHESIVE_CODE_CREATE,
    ADHESIVE_CODE_DELETE,
    ADHESIVE_CODE_HISTORY,
    ADHESIVE_CODE_READ,
    ADHESIVE_CODE_UPDATE,
    ADHESIVE_CREATE,
    ADHESIVE_DELETE,
    ADHESIVE_HISTORY,
    ADHESIVE_READ,
    ADHESIVE_UPDATE,
    ADHESIVES_REPORT_READ,
)
from app.inventory.report_range import resolve_movement_report_range
from app.inventory.schemas import DrumLineHistoryEntry, DrumLineHistorySummary

adhesive_codes_router = APIRouter(prefix="/adhesive-codes", tags=["Adhesive Codes"])
adhesive_brands_router = APIRouter(prefix="/adhesive-brands", tags=["Adhesive Brands"])
adhesives_router = APIRouter(prefix="/adhesives", tags=["Adhesives"])
adhesive_movements_router = APIRouter(prefix="/adhesive-movements", tags=["Adhesive Movements"])
adhesive_lines_router = APIRouter(prefix="/adhesive-lines", tags=["Adhesive Lines"])


@adhesive_codes_router.get("", response_model=ApiResponse[list[AdhesiveCodeResponse]])
async def list_adhesive_codes(
    page: PaginationDependency,
    current_user: ReferenceListAccess,
    service: AdhesiveServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[AdhesiveCodeFilter, Depends()],
    include_column_totals: Annotated[bool, Query()] = False,
) -> ApiResponse[list[AdhesiveCodeResponse]]:
    rows, total = await service.list_codes(
        page=page,
        common_filter=filters,
        is_active=filters.is_active,
    )
    column_totals = None
    if include_column_totals:
        export_rows = await service.list_codes_for_export(
            common_filter=filters,
            is_active=filters.is_active,
        )
        column_totals = await compute_list_column_totals(
            preference_service,
            user_id=current_user.user_id,
            table_key="inventory.adhesive_codes",
            permissions=current_user.permissions,
            rows=export_rows,
        )
    return paginated_response(rows, params=page, total=total, column_totals=column_totals)


@adhesive_codes_router.get("/export", response_class=Response)
async def export_adhesive_codes(
    current_user: ReferenceListAccess,
    service: AdhesiveServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[AdhesiveCodeFilter, Depends()],
    export_scope: ExportScopeQuery,
    format: Annotated[str, Query(pattern="^(csv|xlsx)$")] = "csv",
) -> Response:
    scope_filters = AdhesiveCodeFilter() if is_full_module_export(export_scope) else filters
    rows = await service.list_codes_for_export(
        common_filter=scope_filters,
        is_active=scope_filters.is_active,
    )
    return await export_catalog_table(
        preference_service,
        user_id=current_user.user_id,
        table_key="inventory.adhesive_codes",
        permissions=current_user.permissions,
        filename_stem="adhesive-codes",
        format=format,
        rows=rows,
    )


@adhesive_codes_router.post(
    "",
    response_model=ApiResponse[AdhesiveCodeResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_adhesive_code(
    payload: AdhesiveCodeCreate,
    service: AdhesiveServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_CODE_CREATE))],
) -> ApiResponse[AdhesiveCodeResponse]:
    return ApiResponse(
        data=await service.create_code(payload, actor_user_id=current_user.user_id),
        message="Adhesive code created successfully",
    )


@adhesive_codes_router.get("/{adhesive_code_id}/usage/export", response_class=Response)
async def export_adhesive_code_usage(
    adhesive_code_id: UUID,
    current_user: CurrentUserDependency,
    service: AdhesiveServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_CODE_READ))],
    export_scope: ExportScopeQuery,
    format: Annotated[str, Query(pattern="^(csv|xlsx)$")] = "csv",
) -> Response:
    rows = await service.code_usage_for_export(
        adhesive_code_id,
        permissions=current_user.permissions,
    )
    return await export_catalog_table(
        preference_service,
        user_id=current_user.user_id,
        table_key="inventory.adhesive_code_usage",
        permissions=current_user.permissions,
        filename_stem="adhesive-code-usage",
        format=format,
        rows=rows,
    )


@adhesive_codes_router.get("/{adhesive_code_id}", response_model=ApiResponse[AdhesiveCodeResponse])
async def get_adhesive_code(
    adhesive_code_id: UUID,
    service: AdhesiveServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_CODE_READ))],
) -> ApiResponse[AdhesiveCodeResponse]:
    return ApiResponse(data=await service.get_code(adhesive_code_id))


@adhesive_codes_router.get(
    "/{adhesive_code_id}/usage", response_model=ApiResponse[AdhesiveCodeUsageResponse]
)
async def get_adhesive_code_usage(
    adhesive_code_id: UUID,
    service: AdhesiveServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_CODE_READ))],
) -> ApiResponse[AdhesiveCodeUsageResponse]:
    return ApiResponse(
        data=await service.code_usage(adhesive_code_id, permissions=current_user.permissions),
    )


@adhesive_codes_router.patch(
    "/{adhesive_code_id}", response_model=ApiResponse[AdhesiveCodeResponse]
)
async def update_adhesive_code(
    adhesive_code_id: UUID,
    payload: AdhesiveCodeUpdate,
    service: AdhesiveServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_CODE_UPDATE))],
) -> ApiResponse[AdhesiveCodeResponse]:
    return ApiResponse(
        data=await service.update_code(
            adhesive_code_id, payload, actor_user_id=current_user.user_id
        ),
        message="Adhesive code updated successfully",
    )


@adhesive_codes_router.get(
    "/{adhesive_code_id}/history", response_model=ApiResponse[list[EntityHistoryEntry]]
)
async def adhesive_code_history(
    adhesive_code_id: UUID,
    page: PaginationDependency,
    service: AdhesiveServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_CODE_HISTORY))],
) -> ApiResponse[list[EntityHistoryEntry]]:
    rows, total = await service.code_history(adhesive_code_id, page=page)
    return paginated_response(rows, params=page, total=total)


@adhesive_codes_router.delete(
    "/{adhesive_code_id}", response_model=ApiResponse[AdhesiveCodeResponse]
)
async def delete_adhesive_code(
    adhesive_code_id: UUID,
    service: AdhesiveServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_CODE_DELETE))],
) -> ApiResponse[AdhesiveCodeResponse]:
    return ApiResponse(
        data=await service.delete_code(adhesive_code_id, actor_user_id=current_user.user_id),
        message="Adhesive code deleted successfully",
    )


@adhesive_brands_router.get("", response_model=ApiResponse[list[AdhesiveBrandResponse]])
async def list_adhesive_brands(
    page: PaginationDependency,
    current_user: ReferenceListAccess,
    service: AdhesiveServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[AdhesiveBrandFilter, Depends()],
    include_column_totals: Annotated[bool, Query()] = False,
) -> ApiResponse[list[AdhesiveBrandResponse]]:
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
            table_key="inventory.adhesive_brands",
            permissions=current_user.permissions,
            rows=export_rows,
        )
    return paginated_response(rows, params=page, total=total, column_totals=column_totals)


@adhesive_brands_router.get("/export", response_class=Response)
async def export_adhesive_brands(
    current_user: ReferenceListAccess,
    service: AdhesiveServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[AdhesiveBrandFilter, Depends()],
    export_scope: ExportScopeQuery,
    format: Annotated[str, Query(pattern="^(csv|xlsx)$")] = "csv",
) -> Response:
    scope_filters = AdhesiveBrandFilter() if is_full_module_export(export_scope) else filters
    rows = await service.list_brands_for_export(
        common_filter=scope_filters,
        is_active=scope_filters.is_active,
    )
    return await export_catalog_table(
        preference_service,
        user_id=current_user.user_id,
        table_key="inventory.adhesive_brands",
        permissions=current_user.permissions,
        filename_stem="adhesive-brands",
        format=format,
        rows=rows,
    )


@adhesive_brands_router.post(
    "",
    response_model=ApiResponse[AdhesiveBrandResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_adhesive_brand(
    payload: AdhesiveBrandCreate,
    service: AdhesiveServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_CREATE))],
) -> ApiResponse[AdhesiveBrandResponse]:
    return ApiResponse(
        data=await service.create_brand(payload), message="Adhesive brand created successfully"
    )


@adhesive_brands_router.get("/{brand_id}", response_model=ApiResponse[AdhesiveBrandResponse])
async def get_adhesive_brand(
    brand_id: UUID,
    service: AdhesiveServiceDependency,
    _: ReferenceListAccess,
) -> ApiResponse[AdhesiveBrandResponse]:
    return ApiResponse(data=await service.get_brand(brand_id))


@adhesive_brands_router.patch("/{brand_id}", response_model=ApiResponse[AdhesiveBrandResponse])
async def update_adhesive_brand(
    brand_id: UUID,
    payload: AdhesiveBrandUpdate,
    service: AdhesiveServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_UPDATE))],
) -> ApiResponse[AdhesiveBrandResponse]:
    return ApiResponse(
        data=await service.update_brand(brand_id, payload),
        message="Adhesive brand updated successfully",
    )


@adhesive_brands_router.delete("/{brand_id}", response_model=ApiResponse[AdhesiveBrandResponse])
async def delete_adhesive_brand(
    brand_id: UUID,
    service: AdhesiveServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_DELETE))],
) -> ApiResponse[AdhesiveBrandResponse]:
    return ApiResponse(
        data=await service.delete_brand(brand_id), message="Adhesive brand deleted successfully"
    )


@adhesives_router.get("", response_model=ApiResponse[list[AdhesiveLineListItem]])
async def list_adhesives(
    page: PaginationDependency,
    service: AdhesiveServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[AdhesiveSheetFilter, Depends()],
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_READ))],
    include_column_totals: Annotated[bool, Query()] = False,
) -> ApiResponse[list[AdhesiveLineListItem]]:
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
            table_key="inventory.adhesives",
            permissions=current_user.permissions,
            rows=export_rows,
        )
    return paginated_response(rows, params=page, total=total, column_totals=column_totals)


@adhesives_router.get("/export", response_class=Response)
async def export_adhesives(
    current_user: CurrentUserDependency,
    service: AdhesiveServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[AdhesiveSheetFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_READ))],
    export_scope: ExportScopeQuery,
    format: Annotated[str, Query(pattern="^(csv|xlsx)$")] = "csv",
) -> Response:
    scope_filters = AdhesiveSheetFilter() if is_full_module_export(export_scope) else filters
    rows = await service.list_line_items_for_export(
        common_filter=scope_filters,
        company_id=scope_filters.company_id,
        permissions=current_user.permissions,
    )
    return await export_catalog_table(
        preference_service,
        user_id=current_user.user_id,
        table_key="inventory.adhesives",
        permissions=current_user.permissions,
        filename_stem="adhesives",
        format=format,
        rows=rows,
    )


@adhesives_router.post(
    "",
    response_model=ApiResponse[AdhesiveSheetResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_adhesive_sheet(
    payload: AdhesiveSheetCreate,
    service: AdhesiveServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_CREATE))],
) -> ApiResponse[AdhesiveSheetResponse]:
    row = await service.create_sheet(
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Adhesive sheet created successfully")


@adhesives_router.get("/{sheet_id}", response_model=ApiResponse[AdhesiveSheetResponse])
async def get_adhesive_sheet(
    sheet_id: UUID,
    service: AdhesiveServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_READ))],
) -> ApiResponse[AdhesiveSheetResponse]:
    return ApiResponse(data=await service.get_sheet(sheet_id, permissions=current_user.permissions))


@adhesives_router.patch("/{sheet_id}", response_model=ApiResponse[AdhesiveSheetResponse])
async def update_adhesive_sheet(
    sheet_id: UUID,
    payload: AdhesiveSheetUpdate,
    service: AdhesiveServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_UPDATE))],
) -> ApiResponse[AdhesiveSheetResponse]:
    row = await service.update_sheet(
        sheet_id,
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Adhesive sheet updated successfully")


@adhesives_router.delete("/{sheet_id}", response_model=ApiResponse[AdhesiveSheetResponse])
async def delete_adhesive_sheet(
    sheet_id: UUID,
    service: AdhesiveServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_DELETE))],
) -> ApiResponse[AdhesiveSheetResponse]:
    return ApiResponse(
        data=await service.delete_sheet(sheet_id, actor_user_id=current_user.user_id),
        message="Adhesive sheet deleted successfully",
    )


@adhesives_router.get("/{sheet_id}/history", response_model=ApiResponse[list[EntityHistoryEntry]])
async def adhesive_sheet_history(
    sheet_id: UUID,
    page: PaginationDependency,
    service: AdhesiveServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_HISTORY))],
) -> ApiResponse[list[EntityHistoryEntry]]:
    rows, total = await service.sheet_history(sheet_id, page=page)
    return paginated_response(rows, params=page, total=total)


@adhesives_router.post("/{sheet_id}/stock-out", response_model=ApiResponse[AdhesiveLineResponse])
async def adhesive_stock_out(
    sheet_id: UUID,
    payload: AdhesiveStockOutCreate,
    service: AdhesiveServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_UPDATE))],
) -> ApiResponse[AdhesiveLineResponse]:
    row = await service.stock_out(
        sheet_id,
        payload,
        actor_user_id=current_user.user_id,
    )
    return ApiResponse(data=row, message="Stock out recorded successfully")


@adhesive_lines_router.get(
    "/{line_id}/history", response_model=ApiResponse[list[DrumLineHistoryEntry]]
)
async def adhesive_line_history(
    line_id: UUID,
    page: PaginationDependency,
    service: AdhesiveServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_HISTORY))],
) -> ApiResponse[list[DrumLineHistoryEntry]]:
    rows, total = await service.line_history(
        line_id,
        page=page,
        permissions=current_user.permissions,
    )
    return paginated_response(rows, params=page, total=total)


@adhesive_lines_router.get(
    "/{line_id}/history-summary",
    response_model=ApiResponse[DrumLineHistorySummary],
)
async def adhesive_line_history_summary(
    line_id: UUID,
    service: AdhesiveServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_HISTORY))],
) -> ApiResponse[DrumLineHistorySummary]:
    return ApiResponse(
        data=await service.line_history_summary(line_id, permissions=current_user.permissions),
    )


@adhesive_movements_router.get("/report", response_model=ApiResponse[list[AdhesiveDayReportRow]])
async def adhesive_movement_day_report(
    service: AdhesiveServiceDependency,
    current_user: CurrentUserDependency,
    preference_service: TablePreferenceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVES_REPORT_READ))],
    report_date: Annotated[date | None, Query(alias="date")] = None,
    start_date: Annotated[date | None, Query(alias="start_date")] = None,
    end_date: Annotated[date | None, Query(alias="end_date")] = None,
    include_column_totals: Annotated[bool, Query()] = False,
) -> ApiResponse[list[AdhesiveDayReportRow]]:
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
            table_key="inventory.adhesives_report",
            permissions=current_user.permissions,
            rows=rows,
        )
    return ApiResponse(data=rows, meta=meta)


@adhesive_movements_router.get("/report/export", response_class=Response)
async def export_adhesive_day_report(
    current_user: CurrentUserDependency,
    service: AdhesiveServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVES_REPORT_READ))],
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
    rows = await service.adhesives_day_report_for_export(
        start_date=start,
        end_date=end,
        permissions=current_user.permissions,
    )
    return await export_catalog_table(
        preference_service,
        user_id=current_user.user_id,
        table_key="inventory.adhesives_report",
        permissions=current_user.permissions,
        filename_stem="adhesives-report",
        format=format,
        rows=rows,
    )
