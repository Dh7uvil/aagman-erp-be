"""Inventory HTTP routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response

from app.common.dependencies.auth import CurrentUser, CurrentUserDependency
from app.common.dependencies.export_scope import ExportScopeQuery, is_full_module_export
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import ReferenceListAccess, require_permission
from app.common.export.service import compute_list_column_totals, export_catalog_table
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.table_preferences.dependencies import TablePreferenceServiceDependency
from app.inventory.catalog import (
    MATERIAL_CREATE,
    MATERIAL_DELETE,
    MATERIAL_HISTORY,
    MATERIAL_READ,
    MATERIAL_UPDATE,
    MATERIALS_REPORT_READ,
    UNIT_CREATE,
    UNIT_DELETE,
    UNIT_READ,
    UNIT_UPDATE,
)
from app.inventory.dependencies import InventoryServiceDependency
from app.common.export.report_range import resolve_export_report_range
from app.inventory.report_range import resolve_movement_report_range
from app.inventory.schemas import (
    CategoryCreate,
    CategoryFilter,
    CategoryResponse,
    CategoryUpdate,
    DayReportRow,
    MaterialCreate,
    MaterialFilter,
    MaterialHistoryEntry,
    MaterialHistorySummary,
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

from app.inventory.adhesives.router import (
    adhesive_brands_router,
    adhesive_codes_router,
    adhesive_lines_router,
    adhesive_movements_router,
    adhesives_router,
)
from app.inventory.cylinders.router import cylinders_router, returns_router
from app.inventory.dashboard.router import dashboard_router
from app.inventory.inks.router import (
    ink_brands_router,
    ink_colors_router,
    ink_lines_router,
    ink_movements_router,
    inks_router,
)
from app.inventory.solvents.router import (
    solvent_brands_router,
    solvent_lines_router,
    solvent_movements_router,
    solvent_names_router,
    solvents_router,
)

router = APIRouter(prefix="/inventory", tags=["Inventory"])
router.include_router(units_router)
router.include_router(categories_router)
router.include_router(microns_router)
router.include_router(materials_router)
router.include_router(movements_router)
router.include_router(cylinders_router)
router.include_router(returns_router)
router.include_router(dashboard_router)
router.include_router(ink_colors_router)
router.include_router(ink_brands_router)
router.include_router(inks_router)
router.include_router(ink_lines_router)
router.include_router(ink_movements_router)
router.include_router(adhesive_codes_router)
router.include_router(adhesive_brands_router)
router.include_router(adhesives_router)
router.include_router(adhesive_lines_router)
router.include_router(adhesive_movements_router)
router.include_router(solvent_names_router)
router.include_router(solvent_brands_router)
router.include_router(solvents_router)
router.include_router(solvent_lines_router)
router.include_router(solvent_movements_router)


@units_router.get("", response_model=ApiResponse[list[UnitResponse]])
async def list_units(
    page: PaginationDependency,
    current_user: ReferenceListAccess,
    service: InventoryServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[UnitFilter, Depends()],
    include_column_totals: Annotated[bool, Query()] = False,
) -> ApiResponse[list[UnitResponse]]:
    rows, total = await service.list_units(
        page=page,
        common_filter=filters,
        is_active=filters.is_active,
    )
    column_totals = None
    if include_column_totals:
        export_rows = await service.list_units_for_export(
            common_filter=filters,
            is_active=filters.is_active,
        )
        column_totals = await compute_list_column_totals(
            preference_service,
            user_id=current_user.user_id,
            table_key="inventory.units",
            permissions=current_user.permissions,
            rows=export_rows,
        )
    return paginated_response(rows, params=page, total=total, column_totals=column_totals)


@units_router.get("/export", response_class=Response)
async def export_units(
    current_user: ReferenceListAccess,
    service: InventoryServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[UnitFilter, Depends()],
    export_scope: ExportScopeQuery,
    format: Annotated[str, Query(pattern="^(csv|xlsx)$")] = "csv",
) -> Response:
    scope_filters = UnitFilter() if is_full_module_export(export_scope) else filters
    rows = await service.list_units_for_export(
        common_filter=scope_filters,
        is_active=scope_filters.is_active,
    )
    return await export_catalog_table(
        preference_service,
        user_id=current_user.user_id,
        table_key="inventory.units",
        permissions=current_user.permissions,
        filename_stem="units",
        format=format,
        rows=rows,
    )


@units_router.post(
    "", response_model=ApiResponse[UnitResponse], status_code=status.HTTP_201_CREATED
)
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
    return ApiResponse(
        data=await service.update_unit(unit_id, payload), message="Unit updated successfully"
    )


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
        company_id=filters.company_id,
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
    return ApiResponse(
        data=await service.get_micron(micron_id, permissions=current_user.permissions)
    )


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
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[MaterialFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_READ))],
    include_column_totals: Annotated[bool, Query()] = False,
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
        company_id=filters.company_id,
        permissions=current_user.permissions,
    )
    column_totals = None
    if include_column_totals:
        export_rows = await service.list_materials_for_export(
            common_filter=filters,
            parent_id=filters.parent_id,
            product_id=filters.product_id,
            is_active=filters.is_active,
            size=filters.size,
            rolls=filters.rolls,
            kg_lt=filters.kg_lt,
            kg_gt=filters.kg_gt,
            company_id=filters.company_id,
            permissions=current_user.permissions,
        )
        column_totals = await compute_list_column_totals(
            preference_service,
            user_id=current_user.user_id,
            table_key="inventory.materials",
            permissions=current_user.permissions,
            rows=export_rows,
        )
    return paginated_response(rows, params=page, total=total, column_totals=column_totals)


@materials_router.get("/export", response_class=Response)
async def export_materials(
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    filters: Annotated[MaterialFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_READ))],
    export_scope: ExportScopeQuery,
    format: Annotated[str, Query(pattern="^(csv|xlsx)$")] = "csv",
) -> Response:
    scope_filters = MaterialFilter() if is_full_module_export(export_scope) else filters
    rows = await service.list_materials_for_export(
        common_filter=scope_filters,
        parent_id=scope_filters.parent_id,
        product_id=scope_filters.product_id,
        is_active=scope_filters.is_active,
        size=scope_filters.size,
        rolls=scope_filters.rolls,
        kg_lt=scope_filters.kg_lt,
        kg_gt=scope_filters.kg_gt,
        company_id=scope_filters.company_id,
        permissions=current_user.permissions,
    )
    return await export_catalog_table(
        preference_service,
        user_id=current_user.user_id,
        table_key="inventory.materials",
        permissions=current_user.permissions,
        filename_stem="materials",
        format=format,
        rows=rows,
    )


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


@materials_router.get(
    "/{material_id}/history", response_model=ApiResponse[list[MaterialHistoryEntry]]
)
async def material_history(
    material_id: UUID,
    page: PaginationDependency,
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_HISTORY))],
) -> ApiResponse[list[MaterialHistoryEntry]]:
    rows, total = await service.material_history(
        material_id,
        page=page,
        permissions=current_user.permissions,
    )
    return paginated_response(rows, params=page, total=total)


@materials_router.get(
    "/{material_id}/history-summary",
    response_model=ApiResponse[MaterialHistorySummary],
)
async def material_history_summary(
    material_id: UUID,
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIAL_HISTORY))],
) -> ApiResponse[MaterialHistorySummary]:
    return ApiResponse(
        data=await service.material_history_summary(
            material_id,
            permissions=current_user.permissions,
        ),
    )


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
    row = await service.delete_material(
        material_id,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
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
    preference_service: TablePreferenceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIALS_REPORT_READ))],
    report_date: Annotated[date | None, Query(alias="date")] = None,
    start_date: Annotated[date | None, Query(alias="start_date")] = None,
    end_date: Annotated[date | None, Query(alias="end_date")] = None,
    include_column_totals: Annotated[bool, Query()] = False,
) -> ApiResponse[list[DayReportRow]]:
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
            table_key="inventory.materials_report",
            permissions=current_user.permissions,
            rows=rows,
        )
    return ApiResponse(data=rows, meta=meta)


@movements_router.get("/report/export", response_class=Response)
async def export_materials_day_report(
    current_user: CurrentUserDependency,
    service: InventoryServiceDependency,
    preference_service: TablePreferenceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(MATERIALS_REPORT_READ))],
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
    rows = await service.materials_day_report_for_export(
        start_date=start,
        end_date=end,
        permissions=current_user.permissions,
    )
    return await export_catalog_table(
        preference_service,
        user_id=current_user.user_id,
        table_key="inventory.materials_report",
        permissions=current_user.permissions,
        filename_stem="materials-report",
        format=format,
        rows=rows,
    )


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
    row = await service.create_movement(
        payload,
        actor_user_id=current_user.user_id,
        permissions=current_user.permissions,
    )
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
