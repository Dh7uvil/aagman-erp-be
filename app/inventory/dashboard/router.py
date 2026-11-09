"""Dashboard HTTP routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.common.dependencies.auth import CurrentUser, CurrentUserDependency
from app.common.dependencies.permissions import require_permission
from app.common.schemas.response import ApiResponse
from app.inventory.catalog import ADHESIVE_READ, CYLINDER_READ, INK_READ, MATERIAL_READ, SOLVENT_READ
from app.inventory.dashboard.dependencies import DashboardServiceDependency
from app.inventory.dashboard.schemas import (
    DashboardRange,
    CylindersDashboard,
    AdhesivesDashboard,
    InksDashboard,
    MaterialsDashboard,
    SolventsDashboard,
)

dashboard_router = APIRouter(prefix="/dashboard", tags=["Inventory Dashboard"])


@dashboard_router.get("/cylinders", response_model=ApiResponse[CylindersDashboard])
async def cylinders_dashboard(
    service: DashboardServiceDependency,
    range_params: Annotated[DashboardRange, Depends()],
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CYLINDER_READ))],
) -> ApiResponse[CylindersDashboard]:
    return ApiResponse(
        data=await service.cylinders_overview(
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


@dashboard_router.get("/inks", response_model=ApiResponse[InksDashboard])
async def inks_dashboard(
    service: DashboardServiceDependency,
    range_params: Annotated[DashboardRange, Depends()],
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(INK_READ))],
) -> ApiResponse[InksDashboard]:
    return ApiResponse(
        data=await service.inks_overview(
            range_params=range_params,
            permissions=current_user.permissions,
        )
    )


@dashboard_router.get("/adhesives", response_model=ApiResponse[AdhesivesDashboard])
async def adhesives_dashboard(
    service: DashboardServiceDependency,
    range_params: Annotated[DashboardRange, Depends()],
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ADHESIVE_READ))],
) -> ApiResponse[AdhesivesDashboard]:
    return ApiResponse(
        data=await service.adhesives_overview(
            range_params=range_params,
            permissions=current_user.permissions,
        )
    )


@dashboard_router.get("/solvents", response_model=ApiResponse[SolventsDashboard])
async def solvents_dashboard(
    service: DashboardServiceDependency,
    range_params: Annotated[DashboardRange, Depends()],
    current_user: CurrentUserDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SOLVENT_READ))],
) -> ApiResponse[SolventsDashboard]:
    return ApiResponse(
        data=await service.solvents_overview(
            range_params=range_params,
            permissions=current_user.permissions,
        )
    )
