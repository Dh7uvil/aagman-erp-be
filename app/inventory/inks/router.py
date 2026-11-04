"""Ink HTTP routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response

from app.common.dependencies.auth import CurrentUser, CurrentUserDependency
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import ReferenceListAccess, require_permission
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.services.entity_history import EntityHistoryEntry
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
    InkSheetCreate,
    InkSheetFilter,
    InkLineListItem,
    InkSheetResponse,
    InkSheetUpdate,
    InkStockOutCreate,
    InkLineResponse,
)

ink_colors_router = APIRouter(prefix="/ink-colors", tags=["Ink Colors"])
ink_brands_router = APIRouter(prefix="/ink-brands", tags=["Ink Brands"])
inks_router = APIRouter(prefix="/inks", tags=["Inks"])
ink_movements_router = APIRouter(prefix="/ink-movements", tags=["Ink Movements"])


@ink_colors_router.get("", response_model=ApiResponse[list[InkColorResponse]])
async def list_ink_colors(
    page: PaginationDependency,
    service: InkServiceDependency,
    filters: Annotated[InkColorFilter, Depends()],
    _: ReferenceListAccess,
) -> ApiResponse[list[InkColorResponse]]:
    rows, total = await service.list_colors(
        page=page,
        common_filter=filters,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


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
    service: InkServiceDependency,
    filters: Annotated[InkBrandFilter, Depends()],
    _: ReferenceListAccess,
) -> ApiResponse[list[InkBrandResponse]]:
    rows, total = await service.list_brands(
        page=page,
        common_filter=filters,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


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
    return ApiResponse(data=await service.create_brand(payload), message="Ink brand created successfully")


@ink_brands_router.patch("/{brand_id}", response_model=ApiResponse[InkBrandResponse])
async def update_ink_brand(
    brand_id: UUID,
    payload: InkBrandUpdate,
    service: InkServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_UPDATE))],
) -> ApiResponse[InkBrandResponse]:
    return ApiResponse(data=await service.update_brand(brand_id, payload), message="Ink brand updated successfully")


@ink_brands_router.delete("/{brand_id}", response_model=ApiResponse[InkBrandResponse])
async def delete_ink_brand(
    brand_id: UUID,
    service: InkServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_DELETE))],
) -> ApiResponse[InkBrandResponse]:
    return ApiResponse(data=await service.delete_brand(brand_id), message="Ink brand deleted successfully")


@inks_router.get("", response_model=ApiResponse[list[InkLineListItem]])
async def list_inks(
    page: PaginationDependency,
    service: InkServiceDependency,
    filters: Annotated[InkSheetFilter, Depends()],
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_READ))],
) -> ApiResponse[list[InkLineListItem]]:
    rows, total = await service.list_line_items(
        page=page,
        common_filter=filters,
        company_id=filters.company_id,
        permissions=current_user.permissions,
    )
    return paginated_response(rows, params=page, total=total)


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


@ink_movements_router.get("/report", response_model=ApiResponse[list[InkDayReportRow]])
async def ink_movement_day_report(
    service: InkServiceDependency,
    current_user: CurrentUserDependency,
    report_date: Annotated[date, Query(alias="date")],
    _: Annotated[CurrentUser, Depends(require_permission(INKS_REPORT_READ))],
) -> ApiResponse[list[InkDayReportRow]]:
    return ApiResponse(
        data=await service.day_report(report_date=report_date, permissions=current_user.permissions),
    )
