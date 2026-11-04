"""Solvent HTTP routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.common.dependencies.auth import CurrentUser, CurrentUserDependency
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import ReferenceListAccess, require_permission
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.services.entity_history import EntityHistoryEntry
from app.inventory.report_range import resolve_movement_report_range
from app.inventory.schemas import DrumLineHistoryEntry, DrumLineHistorySummary
from app.inventory.catalog import (
    SOLVENT_NAME_CREATE,
    SOLVENT_NAME_DELETE,
    SOLVENT_NAME_HISTORY,
    SOLVENT_NAME_READ,
    SOLVENT_NAME_UPDATE,
    SOLVENT_CREATE,
    SOLVENT_DELETE,
    SOLVENT_HISTORY,
    SOLVENT_READ,
    SOLVENT_UPDATE,
    SOLVENTS_REPORT_READ,
)
from app.inventory.solvents.dependencies import SolventServiceDependency
from app.inventory.solvents.schemas import (
    SolventBrandCreate,
    SolventBrandFilter,
    SolventBrandResponse,
    SolventBrandUpdate,
    SolventNameCreate,
    SolventNameFilter,
    SolventNameResponse,
    SolventNameUpdate,
    SolventNameUsageResponse,
    SolventDayReportRow,
    SolventSheetCreate,
    SolventSheetFilter,
    SolventLineListItem,
    SolventSheetResponse,
    SolventSheetUpdate,
    SolventStockOutCreate,
    SolventLineResponse,
)

solvent_names_router = APIRouter(prefix="/solvent-names", tags=["Solvent Names"])
solvent_brands_router = APIRouter(prefix="/solvent-brands", tags=["Solvent Brands"])
solvents_router = APIRouter(prefix="/solvents", tags=["Solvents"])
solvent_movements_router = APIRouter(prefix="/solvent-movements", tags=["Solvent Movements"])
solvent_lines_router = APIRouter(prefix="/solvent-lines", tags=["Solvent Lines"])


@solvent_names_router.get("", response_model=ApiResponse[list[SolventNameResponse]])
async def list_solvent_names(
    page: PaginationDependency,
    service: SolventServiceDependency,
    filters: Annotated[SolventNameFilter, Depends()],
    _: ReferenceListAccess,
) -> ApiResponse[list[SolventNameResponse]]:
    rows, total = await service.list_codes(
        page=page,
        common_filter=filters,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@solvent_names_router.post(
    "",
    response_model=ApiResponse[SolventNameResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_solvent_name(
    payload: SolventNameCreate,
    service: SolventServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_NAME_CREATE))],
) -> ApiResponse[SolventNameResponse]:
    return ApiResponse(
        data=await service.create_code(payload, actor_user_id=current_user.user_id),
        message="Solvent name created successfully",
    )


@solvent_names_router.get("/{solvent_name_id}", response_model=ApiResponse[SolventNameResponse])
async def get_solvent_name(
    solvent_name_id: UUID,
    service: SolventServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_NAME_READ))],
) -> ApiResponse[SolventNameResponse]:
    return ApiResponse(data=await service.get_code(solvent_name_id))


@solvent_names_router.get("/{solvent_name_id}/usage", response_model=ApiResponse[SolventNameUsageResponse])
async def get_solvent_name_usage(
    solvent_name_id: UUID,
    service: SolventServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_NAME_READ))],
) -> ApiResponse[SolventNameUsageResponse]:
    return ApiResponse(
        data=await service.name_usage(solvent_name_id, permissions=current_user.permissions),
    )


@solvent_names_router.patch("/{solvent_name_id}", response_model=ApiResponse[SolventNameResponse])
async def update_solvent_name(
    solvent_name_id: UUID,
    payload: SolventNameUpdate,
    service: SolventServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_NAME_UPDATE))],
) -> ApiResponse[SolventNameResponse]:
    return ApiResponse(
        data=await service.update_code(solvent_name_id, payload, actor_user_id=current_user.user_id),
        message="Solvent name updated successfully",
    )


@solvent_names_router.get("/{solvent_name_id}/history", response_model=ApiResponse[list[EntityHistoryEntry]])
async def solvent_name_history(
    solvent_name_id: UUID,
    page: PaginationDependency,
    service: SolventServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_NAME_HISTORY))],
) -> ApiResponse[list[EntityHistoryEntry]]:
    rows, total = await service.name_history(solvent_name_id, page=page)
    return paginated_response(rows, params=page, total=total)


@solvent_names_router.delete("/{solvent_name_id}", response_model=ApiResponse[SolventNameResponse])
async def delete_solvent_name(
    solvent_name_id: UUID,
    service: SolventServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_NAME_DELETE))],
) -> ApiResponse[SolventNameResponse]:
    return ApiResponse(
        data=await service.delete_code(solvent_name_id, actor_user_id=current_user.user_id),
        message="Solvent name deleted successfully",
    )


@solvent_brands_router.get("", response_model=ApiResponse[list[SolventBrandResponse]])
async def list_solvent_brands(
    page: PaginationDependency,
    service: SolventServiceDependency,
    filters: Annotated[SolventBrandFilter, Depends()],
    _: ReferenceListAccess,
) -> ApiResponse[list[SolventBrandResponse]]:
    rows, total = await service.list_brands(
        page=page,
        common_filter=filters,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@solvent_brands_router.post(
    "",
    response_model=ApiResponse[SolventBrandResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_solvent_brand(
    payload: SolventBrandCreate,
    service: SolventServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_CREATE))],
) -> ApiResponse[SolventBrandResponse]:
    return ApiResponse(data=await service.create_brand(payload), message="Solvent brand created successfully")


@solvent_brands_router.get("/{brand_id}", response_model=ApiResponse[SolventBrandResponse])
async def get_solvent_brand(
    brand_id: UUID,
    service: SolventServiceDependency,
    _: ReferenceListAccess,
) -> ApiResponse[SolventBrandResponse]:
    return ApiResponse(data=await service.get_brand(brand_id))


@solvent_brands_router.patch("/{brand_id}", response_model=ApiResponse[SolventBrandResponse])
async def update_solvent_brand(
    brand_id: UUID,
    payload: SolventBrandUpdate,
    service: SolventServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_UPDATE))],
) -> ApiResponse[SolventBrandResponse]:
    return ApiResponse(data=await service.update_brand(brand_id, payload), message="Solvent brand updated successfully")


@solvent_brands_router.delete("/{brand_id}", response_model=ApiResponse[SolventBrandResponse])
async def delete_solvent_brand(
    brand_id: UUID,
    service: SolventServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_DELETE))],
) -> ApiResponse[SolventBrandResponse]:
    return ApiResponse(data=await service.delete_brand(brand_id), message="Solvent brand deleted successfully")


@solvents_router.get("", response_model=ApiResponse[list[SolventLineListItem]])
async def list_solvents(
    page: PaginationDependency,
    service: SolventServiceDependency,
    filters: Annotated[SolventSheetFilter, Depends()],
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_READ))],
) -> ApiResponse[list[SolventLineListItem]]:
    rows, total = await service.list_line_items(
        page=page,
        common_filter=filters,
        company_id=filters.company_id,
        permissions=current_user.permissions,
    )
    return paginated_response(rows, params=page, total=total)


@solvents_router.post(
    "",
    response_model=ApiResponse[SolventSheetResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_solvent_sheet(
    payload: SolventSheetCreate,
    service: SolventServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_CREATE))],
) -> ApiResponse[SolventSheetResponse]:
    row = await service.create_sheet(
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Solvent sheet created successfully")


@solvents_router.get("/{sheet_id}", response_model=ApiResponse[SolventSheetResponse])
async def get_solvent_sheet(
    sheet_id: UUID,
    service: SolventServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_READ))],
) -> ApiResponse[SolventSheetResponse]:
    return ApiResponse(data=await service.get_sheet(sheet_id, permissions=current_user.permissions))


@solvents_router.patch("/{sheet_id}", response_model=ApiResponse[SolventSheetResponse])
async def update_solvent_sheet(
    sheet_id: UUID,
    payload: SolventSheetUpdate,
    service: SolventServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_UPDATE))],
) -> ApiResponse[SolventSheetResponse]:
    row = await service.update_sheet(
        sheet_id,
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Solvent sheet updated successfully")


@solvents_router.delete("/{sheet_id}", response_model=ApiResponse[SolventSheetResponse])
async def delete_solvent_sheet(
    sheet_id: UUID,
    service: SolventServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_DELETE))],
) -> ApiResponse[SolventSheetResponse]:
    return ApiResponse(
        data=await service.delete_sheet(sheet_id, actor_user_id=current_user.user_id),
        message="Solvent sheet deleted successfully",
    )


@solvents_router.get("/{sheet_id}/history", response_model=ApiResponse[list[EntityHistoryEntry]])
async def solvent_sheet_history(
    sheet_id: UUID,
    page: PaginationDependency,
    service: SolventServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_HISTORY))],
) -> ApiResponse[list[EntityHistoryEntry]]:
    rows, total = await service.sheet_history(sheet_id, page=page)
    return paginated_response(rows, params=page, total=total)



@solvents_router.post("/{sheet_id}/stock-out", response_model=ApiResponse[SolventLineResponse])
async def solvent_stock_out(
    sheet_id: UUID,
    payload: SolventStockOutCreate,
    service: SolventServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_UPDATE))],
) -> ApiResponse[SolventLineResponse]:
    row = await service.stock_out(
        sheet_id,
        payload,
        actor_user_id=current_user.user_id,
    )
    return ApiResponse(data=row, message="Stock out recorded successfully")



@solvent_lines_router.get("/{line_id}/history", response_model=ApiResponse[list[DrumLineHistoryEntry]])
async def solvent_line_history(
    line_id: UUID,
    page: PaginationDependency,
    service: SolventServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_HISTORY))],
) -> ApiResponse[list[DrumLineHistoryEntry]]:
    rows, total = await service.line_history(
        line_id,
        page=page,
        permissions=current_user.permissions,
    )
    return paginated_response(rows, params=page, total=total)


@solvent_lines_router.get(
    "/{line_id}/history-summary",
    response_model=ApiResponse[DrumLineHistorySummary],
)
async def solvent_line_history_summary(
    line_id: UUID,
    service: SolventServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_HISTORY))],
) -> ApiResponse[DrumLineHistorySummary]:
    return ApiResponse(
        data=await service.line_history_summary(line_id, permissions=current_user.permissions),
    )


@solvent_movements_router.get("/report", response_model=ApiResponse[list[SolventDayReportRow]])
async def solvent_movement_day_report(
    service: SolventServiceDependency,
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENTS_REPORT_READ))],
    report_date: Annotated[date | None, Query(alias="date")] = None,
    start_date: Annotated[date | None, Query(alias="start_date")] = None,
    end_date: Annotated[date | None, Query(alias="end_date")] = None,
) -> ApiResponse[list[SolventDayReportRow]]:
    start, end = resolve_movement_report_range(
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
    )
    return ApiResponse(
        data=await service.day_report(
            start_date=start,
            end_date=end,
            permissions=current_user.permissions,
        ),
    )
