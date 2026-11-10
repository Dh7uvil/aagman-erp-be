"""Jobs and cylinder returns HTTP routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response

from app.common.dependencies.auth import CurrentUser, CurrentUserDependency
from app.common.dependencies.export_scope import ExportScopeQuery, is_full_module_export
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.export.service import compute_list_column_totals, export_catalog_table
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.services.entity_history import EntityHistoryEntry
from app.common.table_preferences.dependencies import TablePreferenceServiceDependency
from app.common.utils.files import max_upload_bytes
from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.inventory.catalog import (
    CYLINDER_CREATE,
    CYLINDER_DELETE,
    CYLINDER_HISTORY,
    CYLINDER_READ,
    CYLINDER_RETURN_CREATE,
    CYLINDER_RETURN_DELETE,
    CYLINDER_RETURN_READ,
    CYLINDER_RETURN_UPDATE,
    CYLINDER_UPDATE,
)
from app.inventory.cylinders.dependencies import (
    CylinderReturnServiceDependency,
    CylinderServiceDependency,
)
from app.inventory.cylinders.schemas import (
    CYLINDER_FILE_SLOTS,
    CylinderCreate,
    CylinderFilter,
    CylinderListItem,
    CylinderPauseRequest,
    CylinderResponse,
    CylinderResumeRequest,
    CylinderReturnCreate,
    CylinderReturnFilter,
    CylinderReturnResponse,
    CylinderReturnUpdate,
    CylinderUpdate,
)

cylinders_router = APIRouter(prefix="/cylinders", tags=["Cylinders"])
returns_router = APIRouter(prefix="/cylinder-returns", tags=["Cylinder Returns"])

_READ_CHUNK_SIZE = 64 * 1024


async def _read_upload(file: UploadFile, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValidationError(
                "File exceeds the maximum upload size",
                details={"max_bytes": max_bytes},
            )
        chunks.append(chunk)
    return b"".join(chunks)


@cylinders_router.get("", response_model=ApiResponse[list[CylinderListItem]])
async def list_cylinders(
    page: PaginationDependency,
    service: CylinderServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[CylinderFilter, Depends()],
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_READ))],
    include_column_totals: Annotated[bool, Query()] = False,
) -> ApiResponse[list[CylinderListItem]]:
    rows, total = await service.list_cylinders(
        page=page,
        common_filter=filters,
        status=filters.status,
        company_id=filters.company_id,
        include_closed=filters.include_closed,
        permissions=current_user.permissions,
    )
    column_totals = None
    if include_column_totals:
        export_rows = await service.list_cylinders_for_export(
            common_filter=filters,
            status=filters.status,
            company_id=filters.company_id,
            include_closed=filters.include_closed,
            permissions=current_user.permissions,
        )
        column_totals = await compute_list_column_totals(
            preference_service,
            user_id=current_user.user_id,
            table_key="inventory.cylinders",
            permissions=current_user.permissions,
            rows=export_rows,
        )
    return paginated_response(rows, params=page, total=total, column_totals=column_totals)


@cylinders_router.get("/export", response_class=Response)
async def export_cylinders(
    current_user: CurrentUserDependency,
    service: CylinderServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[CylinderFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_READ))],
    export_scope: ExportScopeQuery,
    format: Annotated[str, Query(pattern="^(csv|xlsx)$")] = "csv",
) -> Response:
    scope_filters = CylinderFilter() if is_full_module_export(export_scope) else filters
    rows = await service.list_cylinders_for_export(
        common_filter=scope_filters,
        status=scope_filters.status,
        company_id=scope_filters.company_id,
        include_closed=scope_filters.include_closed,
        permissions=current_user.permissions,
    )
    return await export_catalog_table(
        preference_service,
        user_id=current_user.user_id,
        table_key="inventory.cylinders",
        permissions=current_user.permissions,
        filename_stem="cylinders",
        format=format,
        rows=rows,
    )


@cylinders_router.post(
    "", response_model=ApiResponse[CylinderResponse], status_code=status.HTTP_201_CREATED
)
async def create_cylinder(
    payload: CylinderCreate,
    current_user: CurrentUserDependency,
    service: CylinderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_CREATE))],
) -> ApiResponse[CylinderResponse]:
    row = await service.create_cylinder(
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Cylinder created successfully")


@cylinders_router.get("/{cylinder_id}", response_model=ApiResponse[CylinderResponse])
async def get_cylinder(
    cylinder_id: UUID,
    current_user: CurrentUserDependency,
    service: CylinderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_READ))],
) -> ApiResponse[CylinderResponse]:
    return ApiResponse(
        data=await service.get_cylinder(cylinder_id, permissions=current_user.permissions)
    )


@cylinders_router.patch("/{cylinder_id}", response_model=ApiResponse[CylinderResponse])
async def update_cylinder(
    cylinder_id: UUID,
    payload: CylinderUpdate,
    current_user: CurrentUserDependency,
    service: CylinderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_UPDATE))],
) -> ApiResponse[CylinderResponse]:
    row = await service.update_cylinder(
        cylinder_id,
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Cylinder updated successfully")


@cylinders_router.delete("/{cylinder_id}", response_model=ApiResponse[CylinderResponse])
async def delete_cylinder(
    cylinder_id: UUID,
    current_user: CurrentUserDependency,
    service: CylinderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_DELETE))],
) -> ApiResponse[CylinderResponse]:
    row = await service.delete_cylinder(cylinder_id, actor_user_id=current_user.user_id)
    return ApiResponse(data=row, message="Cylinder deleted successfully")


@cylinders_router.post("/{cylinder_id}/pause", response_model=ApiResponse[CylinderResponse])
async def pause_cylinder(
    cylinder_id: UUID,
    payload: CylinderPauseRequest,
    current_user: CurrentUserDependency,
    service: CylinderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_UPDATE))],
) -> ApiResponse[CylinderResponse]:
    row = await service.pause_cylinder(
        cylinder_id,
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Cylinder paused")


@cylinders_router.post("/{cylinder_id}/resume", response_model=ApiResponse[CylinderResponse])
async def resume_cylinder(
    cylinder_id: UUID,
    payload: CylinderResumeRequest,
    current_user: CurrentUserDependency,
    service: CylinderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_UPDATE))],
) -> ApiResponse[CylinderResponse]:
    row = await service.resume_cylinder(
        cylinder_id,
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Cylinder resumed")


@cylinders_router.get(
    "/{cylinder_id}/history", response_model=ApiResponse[list[EntityHistoryEntry]]
)
async def cylinder_history(
    cylinder_id: UUID,
    page: PaginationDependency,
    service: CylinderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_HISTORY))],
) -> ApiResponse[list[EntityHistoryEntry]]:
    rows, total = await service.cylinder_history(cylinder_id, page=page)
    return paginated_response(rows, params=page, total=total)


@cylinders_router.post("/{cylinder_id}/files/{slot}", response_model=ApiResponse[CylinderResponse])
async def upload_cylinder_file(
    cylinder_id: UUID,
    slot: str,
    current_user: CurrentUserDependency,
    service: CylinderServiceDependency,
    file: Annotated[UploadFile, File()],
) -> ApiResponse[CylinderResponse]:
    if slot not in CYLINDER_FILE_SLOTS:
        raise ValidationError("Invalid file slot")
    settings = get_settings()
    content = await _read_upload(
        file,
        max_bytes=max_upload_bytes(settings.max_upload_size_mb),
    )
    row = await service.upload_file(
        cylinder_id,
        slot,
        filename=file.filename,
        content=content,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="File uploaded successfully")


@cylinders_router.get(
    "/{cylinder_id}/history-attachments/{audit_log_id}",
    response_class=Response,
)
async def download_cylinder_history_attachment(
    cylinder_id: UUID,
    audit_log_id: UUID,
    current_user: CurrentUserDependency,
    service: CylinderServiceDependency,
) -> Response:
    body, content_type = await service.read_history_attachment(
        cylinder_id,
        audit_log_id,
        permissions=current_user.permissions,
    )
    return Response(content=body, media_type=content_type)


@cylinders_router.get("/{cylinder_id}/files/{slot}", response_class=Response)
async def download_cylinder_file(
    cylinder_id: UUID,
    slot: str,
    current_user: CurrentUserDependency,
    service: CylinderServiceDependency,
) -> Response:
    body, content_type = await service.read_file(
        cylinder_id,
        slot,
        permissions=current_user.permissions,
    )
    return Response(content=body, media_type=content_type)


@cylinders_router.delete(
    "/{cylinder_id}/files/{slot}", response_model=ApiResponse[CylinderResponse]
)
async def delete_cylinder_file(
    cylinder_id: UUID,
    slot: str,
    current_user: CurrentUserDependency,
    service: CylinderServiceDependency,
) -> ApiResponse[CylinderResponse]:
    row = await service.delete_file(
        cylinder_id,
        slot,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="File deleted successfully")


@returns_router.get("", response_model=ApiResponse[list[CylinderReturnResponse]])
async def list_cylinder_returns(
    page: PaginationDependency,
    current_user: CurrentUserDependency,
    service: CylinderReturnServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[CylinderReturnFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_RETURN_READ))],
    include_column_totals: Annotated[bool, Query()] = False,
) -> ApiResponse[list[CylinderReturnResponse]]:
    rows, total = await service.list_returns(
        page=page,
        common_filter=filters,
        company_id=filters.company_id,
        cylinder_id=filters.cylinder_id,
    )
    column_totals = None
    if include_column_totals:
        export_rows = await service.list_returns_for_export(
            common_filter=filters,
            company_id=filters.company_id,
            cylinder_id=filters.cylinder_id,
        )
        column_totals = await compute_list_column_totals(
            preference_service,
            user_id=current_user.user_id,
            table_key="inventory.cylinder_returns",
            permissions=current_user.permissions,
            rows=export_rows,
        )
    return paginated_response(rows, params=page, total=total, column_totals=column_totals)


@returns_router.get("/export", response_class=Response)
async def export_cylinder_returns(
    current_user: CurrentUserDependency,
    service: CylinderReturnServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[CylinderReturnFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_RETURN_READ))],
    export_scope: ExportScopeQuery,
    format: Annotated[str, Query(pattern="^(csv|xlsx)$")] = "csv",
) -> Response:
    scope_filters = CylinderReturnFilter() if is_full_module_export(export_scope) else filters
    rows = await service.list_returns_for_export(
        common_filter=scope_filters,
        company_id=scope_filters.company_id,
        cylinder_id=scope_filters.cylinder_id,
    )
    return await export_catalog_table(
        preference_service,
        user_id=current_user.user_id,
        table_key="inventory.cylinder_returns",
        permissions=current_user.permissions,
        filename_stem="cylinder-returns",
        format=format,
        rows=rows,
    )


@returns_router.post(
    "",
    response_model=ApiResponse[CylinderReturnResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_cylinder_return(
    payload: CylinderReturnCreate,
    current_user: CurrentUserDependency,
    service: CylinderReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_RETURN_CREATE))],
) -> ApiResponse[CylinderReturnResponse]:
    row = await service.create_return(payload, actor_user_id=current_user.user_id)
    return ApiResponse(data=row, message="Cylinder return created successfully")


@returns_router.get("/{return_id}", response_model=ApiResponse[CylinderReturnResponse])
async def get_cylinder_return(
    return_id: UUID,
    service: CylinderReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_RETURN_READ))],
) -> ApiResponse[CylinderReturnResponse]:
    return ApiResponse(data=await service.get_return(return_id))


@returns_router.patch("/{return_id}", response_model=ApiResponse[CylinderReturnResponse])
async def update_cylinder_return(
    return_id: UUID,
    payload: CylinderReturnUpdate,
    current_user: CurrentUserDependency,
    service: CylinderReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_RETURN_UPDATE))],
) -> ApiResponse[CylinderReturnResponse]:
    row = await service.update_return(
        return_id,
        payload,
        actor_user_id=current_user.user_id,
    )
    return ApiResponse(data=row, message="Cylinder return updated successfully")


@returns_router.delete("/{return_id}", response_model=ApiResponse[CylinderReturnResponse])
async def delete_cylinder_return(
    return_id: UUID,
    current_user: CurrentUserDependency,
    service: CylinderReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_RETURN_DELETE))],
) -> ApiResponse[CylinderReturnResponse]:
    row = await service.delete_return(return_id, actor_user_id=current_user.user_id)
    return ApiResponse(data=row, message="Cylinder return deleted successfully")


@returns_router.get("/{return_id}/history", response_model=ApiResponse[list[EntityHistoryEntry]])
async def cylinder_return_history(
    return_id: UUID,
    page: PaginationDependency,
    service: CylinderReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_RETURN_READ))],
) -> ApiResponse[list[EntityHistoryEntry]]:
    rows, total = await service.return_history(return_id, page=page)
    return paginated_response(rows, params=page, total=total)
