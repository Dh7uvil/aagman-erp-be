"""Dashboard HTTP routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.common.dependencies.auth import CurrentUser, CurrentUserDependency
from app.common.dependencies.permissions import require_permission
from app.common.schemas.response import ApiResponse
from app.inventory.catalog import JOB_READ, MATERIAL_READ
from app.inventory.dashboard.dependencies import DashboardServiceDependency
from app.inventory.dashboard.schemas import DashboardRange, JobsDashboard, MaterialsDashboard

dashboard_router = APIRouter(prefix="/dashboard", tags=["Inventory Dashboard"])


@dashboard_router.get("/jobs", response_model=ApiResponse[JobsDashboard])
async def jobs_dashboard(
    service: DashboardServiceDependency,
    range_params: Annotated[DashboardRange, Depends()],
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOB_READ))],
) -> ApiResponse[JobsDashboard]:
    return ApiResponse(
        data=await service.jobs_overview(
            range_params=range_params,
            permissions=current_user.permissions,
        )
    )


@dashboard_router.get("/materials", response_model=ApiResponse[MaterialsDashboard])
async def materials_dashboard(
    service: DashboardServiceDependency,
    range_params: Annotated[DashboardRange, Depends()],
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_READ))],
) -> ApiResponse[MaterialsDashboard]:
    return ApiResponse(
        data=await service.materials_overview(
            range_params=range_params,
            permissions=current_user.permissions,
        )
    )
