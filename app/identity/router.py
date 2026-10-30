"""HTTP routes for authentication and access management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import Response

from app.common.dependencies.auth import CurrentUser, CurrentUserDependency
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import ReferenceListAccess, require_permission
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.files import max_upload_bytes
from app.core.exceptions import ValidationError
from app.core.rate_limit import client_key, enforce_auth_rate_limit
from app.identity.catalog import (
    AUDIT_LOG_READ,
    BRANCH_CREATE,
    BRANCH_DELETE,
    BRANCH_READ,
    BRANCH_UPDATE,
    DEPARTMENT_CREATE,
    DEPARTMENT_DELETE,
    DEPARTMENT_READ,
    DEPARTMENT_UPDATE,
    SETTINGS_READ,
    SETTINGS_UPDATE,
    PERMISSION_READ,
    ROLE_CREATE,
    ROLE_DELETE,
    ROLE_READ,
    ROLE_UPDATE,
    USER_CREATE,
    USER_DELETE,
    USER_READ,
    USER_UPDATE,
    COMPANY_CREATE,
    COMPANY_DELETE,
    COMPANY_READ,
    COMPANY_UPDATE,
    WAREHOUSE_CREATE,
    WAREHOUSE_DELETE,
    WAREHOUSE_READ,
    WAREHOUSE_UPDATE,
)
from app.identity.dependencies import (
    AuditLogServiceDependency,
    AuthServiceDependency,
    CompanyServiceDependency,
    OrganizationServiceDependency,
    WarehouseServiceDependency,
)
from app.identity.org_service import LOGO_MAX_SIZE_MB
from app.identity.schemas import (
    AdminResetUserPasswordRequest,
    AssignRolesRequest,
    AuditLogDetailResponse,
    AuditLogFilter,
    AuditLogResponse,
    AuditLogSummaryResponse,
    BranchCreate,
    BranchFilter,
    BranchResponse,
    BranchUpdate,
    CompanyCreate,
    CompanyFilter,
    CompanyResponse,
    CompanyUpdate,
    ChangePasswordRequest,
    DepartmentCreate,
    DepartmentFilter,
    DepartmentResponse,
    DepartmentUpdate,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    MeUpdate,
    OrganizationBrandingResponse,
    OrganizationResponse,
    OrganizationUpdate,
    PermissionFilter,
    PermissionMatrixResponse,
    PermissionResponse,
    RefreshRequest,
    ResetPasswordRequest,
    RoleCreate,
    RoleDetailResponse,
    RoleFilter,
    RoleResponse,
    RoleUpdate,
    SetRolePermissionsRequest,
    TokenPairResponse,
    UserCreate,
    UserDetailResponse,
    UserFilter,
    UserResponse,
    UserUpdate,
    WarehouseCreate,
    WarehouseFilter,
    WarehouseResponse,
    WarehouseUpdate,
)

router = APIRouter()

auth_router = APIRouter(prefix="/auth", tags=["Auth"])
users_router = APIRouter(prefix="/users", tags=["Users"])
roles_router = APIRouter(prefix="/roles", tags=["Roles"])
permissions_router = APIRouter(prefix="/permissions", tags=["Permissions"])
organization_router = APIRouter(prefix="/organization", tags=["Organization"])
branches_router = APIRouter(prefix="/branches", tags=["Branches"])
departments_router = APIRouter(prefix="/departments", tags=["Departments"])
warehouses_router = APIRouter(prefix="/warehouses", tags=["Warehouses"])
companies_router = APIRouter(prefix="/companies", tags=["Companies"])
audit_logs_router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


@auth_router.post(
    "/login",
    response_model=ApiResponse[TokenPairResponse],
    summary="Log in",
    description="Authenticate with email and password, then issue tokens.",
)
async def login(
    payload: LoginRequest,
    request: Request,
    service: AuthServiceDependency,
) -> ApiResponse[TokenPairResponse]:
    enforce_auth_rate_limit(f"login:{client_key(request)}:{payload.email}")
    tokens = await service.login(payload)
    return ApiResponse(data=tokens, message="Logged in successfully")


@auth_router.post(
    "/refresh",
    response_model=ApiResponse[TokenPairResponse],
    summary="Refresh session",
)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    service: AuthServiceDependency,
) -> ApiResponse[TokenPairResponse]:
    enforce_auth_rate_limit(f"refresh:{client_key(request)}")
    tokens = await service.refresh(payload.refresh_token)
    return ApiResponse(data=tokens)


@auth_router.post("/logout", response_model=ApiResponse[None], summary="Log out")
async def logout(
    payload: LogoutRequest,
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
) -> ApiResponse[None]:
    await service.logout(user_id=current_user.user_id, refresh_token=payload.refresh_token)
    return ApiResponse(data=None, message="Logged out successfully")


@auth_router.post("/logout-all", response_model=ApiResponse[None], summary="Log out all sessions")
async def logout_all(
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
) -> ApiResponse[None]:
    await service.logout_all(user_id=current_user.user_id)
    return ApiResponse(data=None, message="Logged out from all sessions successfully")


@auth_router.get("/me", response_model=ApiResponse[MeResponse], summary="Current user")
async def me(
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
) -> ApiResponse[MeResponse]:
    data = await service.me(user_id=current_user.user_id)
    return ApiResponse(data=data)


@auth_router.patch("/me", response_model=ApiResponse[MeResponse], summary="Update current user")
async def update_me(
    payload: MeUpdate,
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
) -> ApiResponse[MeResponse]:
    data = await service.update_me(user_id=current_user.user_id, payload=payload)
    return ApiResponse(data=data, message="Profile updated")


@auth_router.post("/change-password", response_model=ApiResponse[TokenPairResponse])
async def change_password(
    payload: ChangePasswordRequest,
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
) -> ApiResponse[TokenPairResponse]:
    tokens = await service.change_password(user_id=current_user.user_id, payload=payload)
    return ApiResponse(data=tokens, message="Password changed successfully")


@auth_router.post("/forgot-password", response_model=ApiResponse[ForgotPasswordResponse])
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    service: AuthServiceDependency,
) -> ApiResponse[ForgotPasswordResponse]:
    enforce_auth_rate_limit(f"forgot-password:{client_key(request)}:{payload.email}")
    data = await service.request_password_reset(payload)
    return ApiResponse(data=data, message=data.message)


@auth_router.post("/reset-password", response_model=ApiResponse[None])
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    service: AuthServiceDependency,
) -> ApiResponse[None]:
    enforce_auth_rate_limit(f"reset-password:{client_key(request)}")
    await service.reset_password(payload)
    return ApiResponse(data=None, message="Password reset successfully")


@users_router.get("", response_model=ApiResponse[list[UserResponse]], summary="List users")
async def list_users(
    page: PaginationDependency,
    service: AuthServiceDependency,
    filters: Annotated[UserFilter, Depends()],
    _: ReferenceListAccess,
    role_ids: Annotated[list[UUID] | None, Query()] = None,
) -> ApiResponse[list[UserResponse]]:
    user_filter = filters
    if role_ids:
        user_filter = filters.model_copy(
            update={"role_ids": list(dict.fromkeys([*(filters.role_ids or []), *role_ids]))},
        )
    users, total = await service.list_users(page=page, user_filter=user_filter)
    return paginated_response(users, params=page, total=total)


@users_router.post("", response_model=ApiResponse[UserDetailResponse], status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(USER_CREATE))],
) -> ApiResponse[UserDetailResponse]:
    user = await service.create_user(payload, actor_user_id=current_user.user_id)
    return ApiResponse(data=user, message="User created successfully")


@users_router.get("/{user_id}", response_model=ApiResponse[UserDetailResponse])
async def get_user(
    user_id: UUID,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(USER_READ))],
) -> ApiResponse[UserDetailResponse]:
    return ApiResponse(data=await service.get_user(user_id))


@users_router.patch("/{user_id}", response_model=ApiResponse[UserDetailResponse])
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(USER_UPDATE))],
) -> ApiResponse[UserDetailResponse]:
    user = await service.update_user(user_id, payload, actor_user_id=current_user.user_id)
    return ApiResponse(data=user, message="User updated successfully")


@users_router.post("/{user_id}/deactivate", response_model=ApiResponse[UserDetailResponse])
async def deactivate_user(
    user_id: UUID,
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(USER_DELETE))],
) -> ApiResponse[UserDetailResponse]:
    user = await service.deactivate_user(user_id, actor_user_id=current_user.user_id)
    return ApiResponse(data=user, message="User deactivated successfully")


@users_router.post("/{user_id}/activate", response_model=ApiResponse[UserDetailResponse])
async def activate_user(
    user_id: UUID,
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(USER_UPDATE))],
) -> ApiResponse[UserDetailResponse]:
    user = await service.activate_user(user_id, actor_user_id=current_user.user_id)
    return ApiResponse(data=user, message="User activated successfully")


@users_router.post("/{user_id}/password-reset", response_model=ApiResponse[UserDetailResponse])
async def admin_reset_user_password(
    user_id: UUID,
    payload: AdminResetUserPasswordRequest,
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(USER_UPDATE))],
) -> ApiResponse[UserDetailResponse]:
    user = await service.admin_reset_user_password(
        user_id,
        payload,
        actor_user_id=current_user.user_id,
    )
    return ApiResponse(data=user, message="User password reset successfully")


@users_router.put("/{user_id}/roles", response_model=ApiResponse[UserDetailResponse])
async def assign_user_roles(
    user_id: UUID,
    payload: AssignRolesRequest,
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(USER_UPDATE))],
) -> ApiResponse[UserDetailResponse]:
    user = await service.assign_roles(user_id, payload, actor_user_id=current_user.user_id)
    return ApiResponse(data=user, message="User roles updated successfully")


@roles_router.get("", response_model=ApiResponse[list[RoleResponse]])
async def list_roles(
    page: PaginationDependency,
    service: AuthServiceDependency,
    filters: Annotated[RoleFilter, Depends()],
    _: ReferenceListAccess,
) -> ApiResponse[list[RoleResponse]]:
    roles, total = await service.list_roles(page=page, common_filter=filters)
    return paginated_response(roles, params=page, total=total)


@roles_router.post("", response_model=ApiResponse[RoleDetailResponse], status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: RoleCreate,
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_CREATE))],
) -> ApiResponse[RoleDetailResponse]:
    role = await service.create_role(
        payload,
        actor_user_id=current_user.user_id,
        actor_permissions=current_user.permissions,
    )
    return ApiResponse(data=role, message="Role created successfully")


@roles_router.get("/{role_id}", response_model=ApiResponse[RoleDetailResponse])
async def get_role(
    role_id: UUID,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_READ))],
) -> ApiResponse[RoleDetailResponse]:
    return ApiResponse(data=await service.get_role(role_id))


@roles_router.patch("/{role_id}", response_model=ApiResponse[RoleDetailResponse])
async def update_role(
    role_id: UUID,
    payload: RoleUpdate,
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_UPDATE))],
) -> ApiResponse[RoleDetailResponse]:
    role = await service.update_role(role_id, payload, actor_user_id=current_user.user_id)
    return ApiResponse(data=role, message="Role updated successfully")


@roles_router.delete("/{role_id}", response_model=ApiResponse[RoleResponse])
async def delete_role(
    role_id: UUID,
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_DELETE))],
) -> ApiResponse[RoleResponse]:
    role = await service.delete_role(role_id, actor_user_id=current_user.user_id)
    return ApiResponse(data=role, message="Role deleted successfully")


@roles_router.put("/{role_id}/permissions", response_model=ApiResponse[RoleDetailResponse])
async def set_role_permissions(
    role_id: UUID,
    payload: SetRolePermissionsRequest,
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_UPDATE))],
) -> ApiResponse[RoleDetailResponse]:
    role = await service.set_role_permissions(
        role_id,
        payload,
        actor_user_id=current_user.user_id,
        actor_permissions=current_user.permissions,
    )
    return ApiResponse(data=role, message="Role permissions updated successfully")


@roles_router.post("/{role_id}/permissions/reset", response_model=ApiResponse[RoleDetailResponse])
async def reset_role_permissions(
    role_id: UUID,
    current_user: CurrentUserDependency,
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ROLE_UPDATE))],
) -> ApiResponse[RoleDetailResponse]:
    role = await service.reset_role_permissions(role_id, actor_user_id=current_user.user_id)
    return ApiResponse(data=role, message="Role permissions reset successfully")


@permissions_router.get("/matrix", response_model=ApiResponse[PermissionMatrixResponse])
async def permission_matrix(
    service: AuthServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PERMISSION_READ))],
    role_id: Annotated[UUID | None, Query()] = None,
) -> ApiResponse[PermissionMatrixResponse]:
    return ApiResponse(data=await service.permission_matrix(role_id=role_id))


@permissions_router.get("", response_model=ApiResponse[list[PermissionResponse]])
async def list_permissions(
    page: PaginationDependency,
    service: AuthServiceDependency,
    filters: Annotated[PermissionFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PERMISSION_READ))],
) -> ApiResponse[list[PermissionResponse]]:
    permissions, total = await service.list_permissions(
        page=page,
        common_filter=filters,
        module=filters.module,
    )
    return paginated_response(permissions, params=page, total=total)


@organization_router.get("/branding", response_model=ApiResponse[OrganizationBrandingResponse])
async def get_organization_branding(
    service: OrganizationServiceDependency,
) -> ApiResponse[OrganizationBrandingResponse]:
    return ApiResponse(data=await service.get_organization_branding())


@organization_router.get("", response_model=ApiResponse[OrganizationResponse])
async def get_organization(
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SETTINGS_READ))],
) -> ApiResponse[OrganizationResponse]:
    return ApiResponse(data=await service.get_organization())


@organization_router.get("/logo", response_class=Response)
async def get_organization_logo(
    service: OrganizationServiceDependency,
) -> Response:
    body, content_type = await service.get_logo()
    return Response(
        content=body,
        media_type=content_type,
        headers={"Cache-Control": "private, no-cache, must-revalidate"},
    )


@organization_router.patch("", response_model=ApiResponse[OrganizationResponse])
async def update_organization(
    payload: OrganizationUpdate,
    current_user: CurrentUserDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SETTINGS_UPDATE))],
) -> ApiResponse[OrganizationResponse]:
    data = await service.update_organization(payload, actor_user_id=current_user.user_id)
    return ApiResponse(data=data, message="Organization updated successfully")


@organization_router.post("/logo", response_model=ApiResponse[OrganizationResponse])
async def upload_organization_logo(
    current_user: CurrentUserDependency,
    service: OrganizationServiceDependency,
    file: Annotated[UploadFile, File()],
    _: Annotated[CurrentUser, Depends(require_permission(SETTINGS_UPDATE))],
) -> ApiResponse[OrganizationResponse]:
    content = await _read_upload(file, max_bytes=max_upload_bytes(LOGO_MAX_SIZE_MB))
    data = await service.upload_logo(
        filename=file.filename,
        content=content,
        actor_user_id=current_user.user_id,
    )
    return ApiResponse(data=data, message="Organization logo updated successfully")


@organization_router.delete("/logo", response_model=ApiResponse[OrganizationResponse])
async def delete_organization_logo(
    current_user: CurrentUserDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SETTINGS_UPDATE))],
) -> ApiResponse[OrganizationResponse]:
    data = await service.delete_logo(actor_user_id=current_user.user_id)
    return ApiResponse(data=data, message="Organization logo deleted successfully")


@branches_router.get("", response_model=ApiResponse[list[BranchResponse]])
async def list_branches(
    page: PaginationDependency,
    service: OrganizationServiceDependency,
    filters: Annotated[BranchFilter, Depends()],
    _: ReferenceListAccess,
) -> ApiResponse[list[BranchResponse]]:
    branches, total = await service.list_branches(
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status is not None else None,
    )
    return paginated_response(branches, params=page, total=total)


@branches_router.post("", response_model=ApiResponse[BranchResponse], status_code=status.HTTP_201_CREATED)
async def create_branch(
    payload: BranchCreate,
    current_user: CurrentUserDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BRANCH_CREATE))],
) -> ApiResponse[BranchResponse]:
    branch = await service.create_branch(payload, actor_user_id=current_user.user_id)
    return ApiResponse(data=branch, message="Branch created successfully")


@branches_router.get("/{branch_id}", response_model=ApiResponse[BranchResponse])
async def get_branch(
    branch_id: UUID,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BRANCH_READ))],
) -> ApiResponse[BranchResponse]:
    return ApiResponse(data=await service.get_branch(branch_id))


@branches_router.patch("/{branch_id}", response_model=ApiResponse[BranchResponse])
async def update_branch(
    branch_id: UUID,
    payload: BranchUpdate,
    current_user: CurrentUserDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BRANCH_UPDATE))],
) -> ApiResponse[BranchResponse]:
    branch = await service.update_branch(branch_id, payload, actor_user_id=current_user.user_id)
    return ApiResponse(data=branch, message="Branch updated successfully")


@branches_router.delete("/{branch_id}", response_model=ApiResponse[BranchResponse])
async def delete_branch(
    branch_id: UUID,
    current_user: CurrentUserDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BRANCH_DELETE))],
) -> ApiResponse[BranchResponse]:
    branch = await service.delete_branch(branch_id, actor_user_id=current_user.user_id)
    return ApiResponse(data=branch, message="Branch deleted successfully")


@departments_router.get("", response_model=ApiResponse[list[DepartmentResponse]])
async def list_departments(
    page: PaginationDependency,
    service: OrganizationServiceDependency,
    filters: Annotated[DepartmentFilter, Depends()],
    _: ReferenceListAccess,
) -> ApiResponse[list[DepartmentResponse]]:
    departments, total = await service.list_departments(
        page=page,
        common_filter=filters,
        branch_id=filters.branch_id,
    )
    return paginated_response(departments, params=page, total=total)


@departments_router.post(
    "",
    response_model=ApiResponse[DepartmentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_department(
    payload: DepartmentCreate,
    current_user: CurrentUserDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEPARTMENT_CREATE))],
) -> ApiResponse[DepartmentResponse]:
    department = await service.create_department(payload, actor_user_id=current_user.user_id)
    return ApiResponse(data=department, message="Department created successfully")


@departments_router.get("/{department_id}", response_model=ApiResponse[DepartmentResponse])
async def get_department(
    department_id: UUID,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEPARTMENT_READ))],
) -> ApiResponse[DepartmentResponse]:
    return ApiResponse(data=await service.get_department(department_id))


@departments_router.patch("/{department_id}", response_model=ApiResponse[DepartmentResponse])
async def update_department(
    department_id: UUID,
    payload: DepartmentUpdate,
    current_user: CurrentUserDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEPARTMENT_UPDATE))],
) -> ApiResponse[DepartmentResponse]:
    department = await service.update_department(
        department_id,
        payload,
        actor_user_id=current_user.user_id,
    )
    return ApiResponse(data=department, message="Department updated successfully")


@departments_router.delete("/{department_id}", response_model=ApiResponse[DepartmentResponse])
async def delete_department(
    department_id: UUID,
    current_user: CurrentUserDependency,
    service: OrganizationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEPARTMENT_DELETE))],
) -> ApiResponse[DepartmentResponse]:
    department = await service.delete_department(department_id, actor_user_id=current_user.user_id)
    return ApiResponse(data=department, message="Department deleted successfully")


@companies_router.get("", response_model=ApiResponse[list[CompanyResponse]])
async def list_companies(
    page: PaginationDependency,
    service: CompanyServiceDependency,
    filters: Annotated[CompanyFilter, Depends()],
    _: ReferenceListAccess,
) -> ApiResponse[list[CompanyResponse]]:
    rows, total = await service.list(page=page, common_filter=filters)
    return paginated_response(rows, params=page, total=total)


@companies_router.post("", response_model=ApiResponse[CompanyResponse], status_code=status.HTTP_201_CREATED)
async def create_company(
    payload: CompanyCreate,
    current_user: CurrentUserDependency,
    service: CompanyServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COMPANY_CREATE))],
) -> ApiResponse[CompanyResponse]:
    row = await service.create(payload, actor_user_id=current_user.user_id)
    return ApiResponse(data=row, message="Company created successfully")


@companies_router.get("/{company_id}", response_model=ApiResponse[CompanyResponse])
async def get_company(
    company_id: UUID,
    service: CompanyServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COMPANY_READ))],
) -> ApiResponse[CompanyResponse]:
    return ApiResponse(data=await service.get(company_id))


@companies_router.patch("/{company_id}", response_model=ApiResponse[CompanyResponse])
async def update_company(
    company_id: UUID,
    payload: CompanyUpdate,
    current_user: CurrentUserDependency,
    service: CompanyServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COMPANY_UPDATE))],
) -> ApiResponse[CompanyResponse]:
    row = await service.update(company_id, payload, actor_user_id=current_user.user_id)
    return ApiResponse(data=row, message="Company updated successfully")


@companies_router.delete("/{company_id}", response_model=ApiResponse[CompanyResponse])
async def delete_company(
    company_id: UUID,
    current_user: CurrentUserDependency,
    service: CompanyServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COMPANY_DELETE))],
) -> ApiResponse[CompanyResponse]:
    row = await service.delete(company_id, actor_user_id=current_user.user_id)
    return ApiResponse(data=row, message="Company deleted successfully")


@warehouses_router.get("", response_model=ApiResponse[list[WarehouseResponse]])
async def list_warehouses(
    page: PaginationDependency,
    service: WarehouseServiceDependency,
    filters: Annotated[WarehouseFilter, Depends()],
    _: ReferenceListAccess,
) -> ApiResponse[list[WarehouseResponse]]:
    rows, total = await service.list(page=page, common_filter=filters)
    return paginated_response(rows, params=page, total=total)


@warehouses_router.post("", response_model=ApiResponse[WarehouseResponse], status_code=status.HTTP_201_CREATED)
async def create_warehouse(
    payload: WarehouseCreate,
    current_user: CurrentUserDependency,
    service: WarehouseServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(WAREHOUSE_CREATE))],
) -> ApiResponse[WarehouseResponse]:
    row = await service.create(payload, actor_user_id=current_user.user_id)
    return ApiResponse(data=row, message="Warehouse created successfully")


@warehouses_router.get("/{warehouse_id}", response_model=ApiResponse[WarehouseResponse])
async def get_warehouse(
    warehouse_id: UUID,
    service: WarehouseServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(WAREHOUSE_READ))],
) -> ApiResponse[WarehouseResponse]:
    return ApiResponse(data=await service.get(warehouse_id))


@warehouses_router.patch("/{warehouse_id}", response_model=ApiResponse[WarehouseResponse])
async def update_warehouse(
    warehouse_id: UUID,
    payload: WarehouseUpdate,
    current_user: CurrentUserDependency,
    service: WarehouseServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(WAREHOUSE_UPDATE))],
) -> ApiResponse[WarehouseResponse]:
    row = await service.update(warehouse_id, payload, actor_user_id=current_user.user_id)
    return ApiResponse(data=row, message="Warehouse updated successfully")


@warehouses_router.delete("/{warehouse_id}", response_model=ApiResponse[WarehouseResponse])
async def delete_warehouse(
    warehouse_id: UUID,
    current_user: CurrentUserDependency,
    service: WarehouseServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(WAREHOUSE_DELETE))],
) -> ApiResponse[WarehouseResponse]:
    row = await service.delete(warehouse_id, actor_user_id=current_user.user_id)
    return ApiResponse(data=row, message="Warehouse deleted successfully")


@audit_logs_router.get("/summary", response_model=ApiResponse[AuditLogSummaryResponse])
async def audit_log_summary(
    service: AuditLogServiceDependency,
    filters: Annotated[AuditLogFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(AUDIT_LOG_READ))],
) -> ApiResponse[AuditLogSummaryResponse]:
    return ApiResponse(data=await service.summarize(common_filter=filters))


@audit_logs_router.get("", response_model=ApiResponse[list[AuditLogResponse]])
async def list_audit_logs(
    page: PaginationDependency,
    service: AuditLogServiceDependency,
    filters: Annotated[AuditLogFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(AUDIT_LOG_READ))],
) -> ApiResponse[list[AuditLogResponse]]:
    rows, total = await service.list_logs(
        page=page,
        common_filter=filters,
        module=filters.module,
        action=filters.action,
        user_id=filters.user_id,
        entity_type=filters.entity_type,
        entity_id=filters.entity_id,
    )
    return paginated_response(rows, params=page, total=total)


@audit_logs_router.get("/export.csv", response_class=Response)
async def export_audit_logs(
    service: AuditLogServiceDependency,
    filters: Annotated[AuditLogFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(AUDIT_LOG_READ))],
) -> Response:
    csv_body = await service.export_csv(
        common_filter=filters,
        module=filters.module,
        action=filters.action,
        user_id=filters.user_id,
        entity_type=filters.entity_type,
        entity_id=filters.entity_id,
    )
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit-logs.csv"'},
    )


@audit_logs_router.get("/{audit_log_id}", response_model=ApiResponse[AuditLogDetailResponse])
async def get_audit_log(
    audit_log_id: UUID,
    service: AuditLogServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(AUDIT_LOG_READ))],
) -> ApiResponse[AuditLogDetailResponse]:
    return ApiResponse(data=await service.get_log(audit_log_id))


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


router.include_router(auth_router)
router.include_router(users_router)
router.include_router(roles_router)
router.include_router(permissions_router)
router.include_router(organization_router)
router.include_router(branches_router)
router.include_router(departments_router)
router.include_router(warehouses_router)
router.include_router(companies_router)
router.include_router(audit_logs_router)
