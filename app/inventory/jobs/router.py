"""Jobs and cylinder returns HTTP routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import Response

from app.common.dependencies.auth import CurrentUser, CurrentUserDependency
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.services.entity_history import EntityHistoryEntry
from app.common.utils.files import max_upload_bytes
from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.inventory.catalog import (
    CYLINDER_RETURN_CREATE,
    CYLINDER_RETURN_DELETE,
    CYLINDER_RETURN_READ,
    CYLINDER_RETURN_UPDATE,
    JOB_CREATE,
    JOB_DELETE,
    JOB_HISTORY,
    JOB_READ,
    JOB_UPDATE,
)
from app.inventory.jobs.dependencies import CylinderReturnServiceDependency, JobServiceDependency
from app.inventory.jobs.schemas import (
    JOB_FILE_SLOTS,
    CylinderReturnCreate,
    CylinderReturnFilter,
    CylinderReturnResponse,
    CylinderReturnUpdate,
    JobCreate,
    JobFilter,
    JobListItem,
    JobPauseRequest,
    JobResponse,
    JobUpdate,
)

jobs_router = APIRouter(prefix="/jobs", tags=["Jobs"])
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


@jobs_router.get("", response_model=ApiResponse[list[JobListItem]])
async def list_jobs(
    page: PaginationDependency,
    service: JobServiceDependency,
    filters: Annotated[JobFilter, Depends()],
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOB_READ))],
) -> ApiResponse[list[JobListItem]]:
    rows, total = await service.list_jobs(
        page=page,
        common_filter=filters,
        status=filters.status,
        company_id=filters.company_id,
        include_closed=filters.include_closed,
        permissions=current_user.permissions,
    )
    return paginated_response(rows, params=page, total=total)


@jobs_router.post("", response_model=ApiResponse[JobResponse], status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreate,
    current_user: CurrentUserDependency,
    service: JobServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOB_CREATE))],
) -> ApiResponse[JobResponse]:
    row = await service.create_job(
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Job created successfully")


@jobs_router.get("/{job_id}", response_model=ApiResponse[JobResponse])
async def get_job(
    job_id: UUID,
    current_user: CurrentUserDependency,
    service: JobServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOB_READ))],
) -> ApiResponse[JobResponse]:
    return ApiResponse(data=await service.get_job(job_id, permissions=current_user.permissions))


@jobs_router.patch("/{job_id}", response_model=ApiResponse[JobResponse])
async def update_job(
    job_id: UUID,
    payload: JobUpdate,
    current_user: CurrentUserDependency,
    service: JobServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOB_UPDATE))],
) -> ApiResponse[JobResponse]:
    row = await service.update_job(
        job_id,
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Job updated successfully")


@jobs_router.delete("/{job_id}", response_model=ApiResponse[JobResponse])
async def delete_job(
    job_id: UUID,
    current_user: CurrentUserDependency,
    service: JobServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOB_DELETE))],
) -> ApiResponse[JobResponse]:
    row = await service.delete_job(job_id, actor_user_id=current_user.user_id)
    return ApiResponse(data=row, message="Job deleted successfully")


@jobs_router.post("/{job_id}/pause", response_model=ApiResponse[JobResponse])
async def pause_job(
    job_id: UUID,
    payload: JobPauseRequest,
    current_user: CurrentUserDependency,
    service: JobServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOB_UPDATE))],
) -> ApiResponse[JobResponse]:
    row = await service.pause_job(
        job_id,
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Job paused")


@jobs_router.post("/{job_id}/resume", response_model=ApiResponse[JobResponse])
async def resume_job(
    job_id: UUID,
    current_user: CurrentUserDependency,
    service: JobServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOB_UPDATE))],
) -> ApiResponse[JobResponse]:
    row = await service.resume_job(
        job_id,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Job resumed")


@jobs_router.get("/{job_id}/history", response_model=ApiResponse[list[EntityHistoryEntry]])
async def job_history(
    job_id: UUID,
    page: PaginationDependency,
    service: JobServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOB_HISTORY))],
) -> ApiResponse[list[EntityHistoryEntry]]:
    rows, total = await service.job_history(job_id, page=page)
    return paginated_response(rows, params=page, total=total)


@jobs_router.post("/{job_id}/files/{slot}", response_model=ApiResponse[JobResponse])
async def upload_job_file(
    job_id: UUID,
    slot: str,
    current_user: CurrentUserDependency,
    service: JobServiceDependency,
    file: Annotated[UploadFile, File()],
) -> ApiResponse[JobResponse]:
    if slot not in JOB_FILE_SLOTS:
        raise ValidationError("Invalid file slot")
    settings = get_settings()
    content = await _read_upload(
        file,
        max_bytes=max_upload_bytes(settings.max_upload_size_mb),
    )
    row = await service.upload_file(
        job_id,
        slot,
        filename=file.filename,
        content=content,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="File uploaded successfully")


@jobs_router.get(
    "/{job_id}/history-attachments/{audit_log_id}",
    response_class=Response,
)
async def download_job_history_attachment(
    job_id: UUID,
    audit_log_id: UUID,
    current_user: CurrentUserDependency,
    service: JobServiceDependency,
) -> Response:
    body, content_type = await service.read_history_attachment(
        job_id,
        audit_log_id,
        permissions=current_user.permissions,
    )
    return Response(content=body, media_type=content_type)


@jobs_router.get("/{job_id}/files/{slot}", response_class=Response)
async def download_job_file(
    job_id: UUID,
    slot: str,
    current_user: CurrentUserDependency,
    service: JobServiceDependency,
) -> Response:
    body, content_type = await service.read_file(
        job_id,
        slot,
        permissions=current_user.permissions,
    )
    return Response(content=body, media_type=content_type)


@jobs_router.delete("/{job_id}/files/{slot}", response_model=ApiResponse[JobResponse])
async def delete_job_file(
    job_id: UUID,
    slot: str,
    current_user: CurrentUserDependency,
    service: JobServiceDependency,
) -> ApiResponse[JobResponse]:
    row = await service.delete_file(
        job_id,
        slot,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="File deleted successfully")


@returns_router.get("", response_model=ApiResponse[list[CylinderReturnResponse]])
async def list_cylinder_returns(
    page: PaginationDependency,
    service: CylinderReturnServiceDependency,
    filters: Annotated[CylinderReturnFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_RETURN_READ))],
) -> ApiResponse[list[CylinderReturnResponse]]:
    rows, total = await service.list_returns(
        page=page,
        common_filter=filters,
        company_id=filters.company_id,
        job_id=filters.job_id,
    )
    return paginated_response(rows, params=page, total=total)


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
