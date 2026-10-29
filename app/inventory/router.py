"""Inventory HTTP routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.common.dependencies.auth import CurrentUser, CurrentUserDependency
from app.common.dependencies.permissions import ReferenceListAccess
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.inventory.catalog import (
    MATERIAL_CREATE,
    MATERIAL_DELETE,
    MATERIAL_READ,
    MATERIAL_UPDATE,
    MATERIALS_REPORT_READ,
    UNIT_CREATE,
    UNIT_DELETE,
    UNIT_READ,
    UNIT_UPDATE,
)
from app.inventory.dependencies import InventoryServiceDependency
from app.inventory.schemas import (
    CategoryCreate,
    CategoryFilter,
    CategoryResponse,
    CategoryUpdate,
    DayReportRow,
    MaterialCreate,
    MaterialFilter,
    MaterialResponse,
    MaterialUpdate,
    MicronCreate,
    MicronFilter,
    MicronResponse,
    MicronUpdate,
    MovementCreate,
    MovementResponse,
    UnitCreate,
    UnitFilter,
    UnitResponse,
    UnitUpdate,
)

units_router = APIRouter(prefix="/units", tags=["Inventory Units"])
categories_router = APIRouter(prefix="/material-categories", tags=["Material Categories"])
microns_router = APIRouter(prefix="/microns", tags=["Material Microns"])
materials_router = APIRouter(prefix="/material-subcategories", tags=["Materials"])
movements_router = APIRouter(prefix="/material-movements", tags=["Material Movements"])

from app.inventory.jobs.router import jobs_router, returns_router

router = APIRouter(prefix="/inventory", tags=["Inventory"])
router.include_router(units_router)
router.include_router(categories_router)
router.include_router(microns_router)
router.include_router(materials_router)
router.include_router(movements_router)
router.include_router(jobs_router)
router.include_router(returns_router)


@units_router.get("", response_model=ApiResponse[list[UnitResponse]])
async def list_units(
    page: PaginationDependency,
    service: InventoryServiceDependency,
    filters: Annotated[UnitFilter, Depends()],
    _: ReferenceListAccess,
) -> ApiResponse[list[UnitResponse]]:
    rows, total = await service.list_units(
        page=page,
        common_filter=filters,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@units_router.post("", response_model=ApiResponse[UnitResponse], status_code=status.HTTP_201_CREATED)
async def create_unit(
    payload: UnitCreate,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(UNIT_CREATE))],
) -> ApiResponse[UnitResponse]:
    return ApiResponse(data=await service.create_unit(payload), message="Unit created successfully")


@units_router.get("/{unit_id}", response_model=ApiResponse[UnitResponse])
async def get_unit(
    unit_id: UUID,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(UNIT_READ))],
) -> ApiResponse[UnitResponse]:
    return ApiResponse(data=await service.get_unit(unit_id))


@units_router.patch("/{unit_id}", response_model=ApiResponse[UnitResponse])
async def update_unit(
    unit_id: UUID,
    payload: UnitUpdate,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(UNIT_UPDATE))],
) -> ApiResponse[UnitResponse]:
    return ApiResponse(data=await service.update_unit(unit_id, payload), message="Unit updated successfully")


@units_router.delete("/{unit_id}", response_model=ApiResponse[UnitResponse])
async def delete_unit(
    unit_id: UUID,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(UNIT_DELETE))],
) -> ApiResponse[UnitResponse]:
    return ApiResponse(data=await service.delete_unit(unit_id), message="Unit deleted successfully")


@categories_router.get("", response_model=ApiResponse[list[CategoryResponse]])
async def list_categories(
    page: PaginationDependency,
    service: InventoryServiceDependency,
    filters: Annotated[CategoryFilter, Depends()],
    _: ReferenceListAccess,
) -> ApiResponse[list[CategoryResponse]]:
    rows, total = await service.list_categories(
        page=page,
        common_filter=filters,
        is_active=filters.is_active,
        roots_only=filters.roots_only,
    )
    return paginated_response(rows, params=page, total=total)


@categories_router.post(
    "",
    response_model=ApiResponse[CategoryResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    payload: CategoryCreate,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_CREATE))],
) -> ApiResponse[CategoryResponse]:
    return ApiResponse(
        data=await service.create_category(payload),
        message="Category created successfully",
    )


@categories_router.get("/{category_id}", response_model=ApiResponse[CategoryResponse])
async def get_category(
    category_id: UUID,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_READ))],
) -> ApiResponse[CategoryResponse]:
    return ApiResponse(data=await service.get_category(category_id))


@categories_router.patch("/{category_id}", response_model=ApiResponse[CategoryResponse])
async def update_category(
    category_id: UUID,
    payload: CategoryUpdate,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_UPDATE))],
) -> ApiResponse[CategoryResponse]:
    return ApiResponse(
        data=await service.update_category(category_id, payload),
        message="Category updated successfully",
    )


@categories_router.delete("/{category_id}", response_model=ApiResponse[CategoryResponse])
async def delete_category(
    category_id: UUID,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_DELETE))],
) -> ApiResponse[CategoryResponse]:
    return ApiResponse(
        data=await service.delete_category(category_id),
        message="Category deleted successfully",
    )


@microns_router.get("", response_model=ApiResponse[list[MicronResponse]])
async def list_microns(
    page: PaginationDependency,
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    filters: Annotated[MicronFilter, Depends()],
    _: ReferenceListAccess,
) -> ApiResponse[list[MicronResponse]]:
    rows, total = await service.list_microns(
        page=page,
        common_filter=filters,
        product_id=filters.product_id,
        is_active=filters.is_active,
        permissions=current_user.permissions,
    )
    return paginated_response(rows, params=page, total=total)


@microns_router.post(
    "",
    response_model=ApiResponse[MicronResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_micron(
    payload: MicronCreate,
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_CREATE))],
) -> ApiResponse[MicronResponse]:
    row = await service.create_micron(payload, permissions=current_user.permissions)
    return ApiResponse(data=row, message="Micron created successfully")


@microns_router.get("/{micron_id}", response_model=ApiResponse[MicronResponse])
async def get_micron(
    micron_id: UUID,
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_READ))],
) -> ApiResponse[MicronResponse]:
    return ApiResponse(data=await service.get_micron(micron_id, permissions=current_user.permissions))


@microns_router.patch("/{micron_id}", response_model=ApiResponse[MicronResponse])
async def update_micron(
    micron_id: UUID,
    payload: MicronUpdate,
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_UPDATE))],
) -> ApiResponse[MicronResponse]:
    row = await service.update_micron(micron_id, payload, permissions=current_user.permissions)
    return ApiResponse(data=row, message="Micron updated successfully")


@microns_router.delete("/{micron_id}", response_model=ApiResponse[MicronResponse])
async def delete_micron(
    micron_id: UUID,
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_DELETE))],
) -> ApiResponse[MicronResponse]:
    row = await service.delete_micron(micron_id, permissions=current_user.permissions)
    return ApiResponse(data=row, message="Micron deleted successfully")


@materials_router.get("", response_model=ApiResponse[list[MaterialResponse]])
async def list_materials(
    page: PaginationDependency,
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    filters: Annotated[MaterialFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_READ))],
) -> ApiResponse[list[MaterialResponse]]:
    rows, total = await service.list_materials(
        page=page,
        common_filter=filters,
        parent_id=filters.parent_id,
        product_id=filters.product_id,
        is_active=filters.is_active,
        size=filters.size,
        rolls=filters.rolls,
        kg_lt=filters.kg_lt,
        kg_gt=filters.kg_gt,
        permissions=current_user.permissions,
    )
    return paginated_response(rows, params=page, total=total)


@materials_router.post(
    "",
    response_model=ApiResponse[MaterialResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_material(
    payload: MaterialCreate,
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_CREATE))],
) -> ApiResponse[MaterialResponse]:
    row = await service.create_material(
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Material created successfully")


@materials_router.get("/{material_id}", response_model=ApiResponse[MaterialResponse])
async def get_material(
    material_id: UUID,
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_READ))],
) -> ApiResponse[MaterialResponse]:
    return ApiResponse(
        data=await service.get_material(material_id, permissions=current_user.permissions),
    )


@materials_router.patch("/{material_id}", response_model=ApiResponse[MaterialResponse])
async def update_material(
    material_id: UUID,
    payload: MaterialUpdate,
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_UPDATE))],
) -> ApiResponse[MaterialResponse]:
    row = await service.update_material(
        material_id,
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Material updated successfully")


@materials_router.delete("/{material_id}", response_model=ApiResponse[MaterialResponse])
async def delete_material(
    material_id: UUID,
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_DELETE))],
) -> ApiResponse[MaterialResponse]:
    row = await service.delete_material(material_id, permissions=current_user.permissions)
    return ApiResponse(data=row, message="Material deleted successfully")


@movements_router.get("", response_model=ApiResponse[list[MovementResponse]])
async def list_movements(
    page: PaginationDependency,
    service: InventoryServiceDependency,
    movement_date: Annotated[date, Query(alias="date")],
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_READ))],
) -> ApiResponse[list[MovementResponse]]:
    rows, total = await service.list_movements(movement_date=movement_date, page=page)
    return paginated_response(rows, params=page, total=total)


@movements_router.get("/report", response_model=ApiResponse[list[DayReportRow]])
async def movement_day_report(
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    report_date: Annotated[date, Query(alias="date")],
    _: Annotated[CurrentUser, Depends(require_permission(MATERIALS_REPORT_READ))],
) -> ApiResponse[list[DayReportRow]]:
    return ApiResponse(data=await service.day_report(report_date=report_date, permissions=current_user.permissions))


@movements_router.get("/{movement_id}", response_model=ApiResponse[MovementResponse])
async def get_movement(
    movement_id: UUID,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_READ))],
) -> ApiResponse[MovementResponse]:
    return ApiResponse(data=await service.get_movement(movement_id))


@movements_router.post(
    "",
    response_model=ApiResponse[MovementResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_movement(
    payload: MovementCreate,
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_UPDATE))],
) -> ApiResponse[MovementResponse]:
    row = await service.create_movement(payload, actor_user_id=current_user.user_id)
    return ApiResponse(data=row, message="Movement recorded successfully")


@movements_router.delete("/{movement_id}", response_model=ApiResponse[MovementResponse])
async def delete_movement(
    movement_id: UUID,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_UPDATE))],
) -> ApiResponse[MovementResponse]:
    return ApiResponse(
        data=await service.delete_movement(movement_id),
        message="Movement removed successfully",
    )
