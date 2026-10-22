"""Business logic for authentication and access management."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter, audit_field_changes
from app.common.utils.datetime import utcnow
from app.core.config import get_settings
from app.core.enums import (
    AuditAction,
    AuditStatus,
    IDENTITY_MODULE,
    SYSTEM_ADMIN_ROLE_NAME,
    UserStatus,
)
from app.core.exceptions import (
    DuplicateResourceError,
    InvalidCredentialsError,
    InvalidStatusTransitionError,
    InvalidTokenError,
    ResourceNotFoundError,
    TokenExpiredError,
    ValidationError,
)
from app.core.permissions import build_permission
from app.core.security import (
    PasswordTooLongError,
    TokenClaims,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    generate_password_reset_token,
    hash_password,
    hash_password_reset_token,
    verify_password,
)
from app.db.session import transaction
from app.identity.catalog import (
    ensure_superadmin,
    get_system_admin_role,
    grant_catalog_to_role,
    seed_permissions,
)
from app.identity.models import Permission, Role, User
from app.identity.org_repository import OrganizationRepository
from app.identity.repository import AccessRepository
from app.identity.schemas import (
    AdminResetUserPasswordRequest,
    AssignRolesRequest,
    BranchSummary,
    ChangePasswordRequest,
    DepartmentSummary,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    MeResponse,
    MeUpdate,
    PermissionMatrixAction,
    PermissionMatrixModule,
    PermissionMatrixResource,
    PermissionMatrixResponse,
    PermissionResponse,
    ResetPasswordRequest,
    RoleCreate,
    RoleDetailResponse,
    RoleResponse,
    RoleSummary,
    RoleUpdate,
    SetRolePermissionsRequest,
    TokenPairResponse,
    UserCreate,
    UserDetailResponse,
    UserFilter,
    UserResponse,
    UserUpdate,
)

logger = logging.getLogger(__name__)


def _role_names(roles: Sequence[Role]) -> list[str]:
    return sorted(role.name for role in roles)


def _permission_codes(permissions: Sequence[Permission]) -> list[str]:
    return sorted(build_permission(item.module, item.resource, item.action) for item in permissions)


def _role_snapshot(role: Role) -> dict[str, object]:
    return {
        "name": role.name,
        "description": role.description,
        "is_system_role": role.is_system_role,
        "record_scope": role.record_scope,
    }


def validate_permission_grant_subset(
    granted_codes: set[str],
    actor_permissions: frozenset[str],
    *,
    actor_is_superadmin: bool,
) -> None:
    if actor_is_superadmin:
        return
    excess = granted_codes - actor_permissions
    if excess:
        raise ValidationError("Cannot grant permissions you do not hold")


class AuthService:
    """Authentication, session, and identity-management use cases."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AccessRepository(session)
        self.org = OrganizationRepository(session)
        self.audit = AuditWriter(session)

    async def login(self, payload: LoginRequest) -> TokenPairResponse:
        failed_user_id: UUID | None = None
        try:
            async with transaction(self.session):
                user = await self.repo.get_user_by_email(payload.email)
                password_hash = user.password_hash if user is not None else None
                credentials_ok = (
                    user is not None
                    and user.status == UserStatus.ACTIVE
                    and password_hash is not None
                    and verify_password(payload.password, password_hash)
                )
                if not credentials_ok or user is None:
                    failed_user_id = user.id if user is not None else None
                    logger.warning("login_failed", extra={"email": payload.email})
                    raise InvalidCredentialsError()

                user.last_login_at = utcnow()
                await self._ensure_catalog()
                tokens = await self._issue_token_pair(user)
                await self.audit.write(
                    user_id=user.id,
                    action=AuditAction.LOGIN,
                    module=IDENTITY_MODULE,
                    entity_type="user",
                    entity_id=user.id,
                    status=AuditStatus.SUCCESS,
                )
                return tokens
        except InvalidCredentialsError:
            async with transaction(self.session):
                await self.audit.write(
                    user_id=failed_user_id,
                    action=AuditAction.LOGIN,
                    module=IDENTITY_MODULE,
                    entity_type="user",
                    entity_id=failed_user_id,
                    status=AuditStatus.FAILED,
                )
            raise

    async def refresh(self, refresh_token: str) -> TokenPairResponse:
        claims = self._decode_refresh(refresh_token)
        if claims.expires_at <= utcnow():
            raise TokenExpiredError()

        async with transaction(self.session):
            stored = await self.repo.get_refresh_token_by_jti(claims.token_id, for_update=True)
            if (
                stored is None
                or stored.revoked_at is not None
                or stored.expires_at <= utcnow()
                or str(stored.user_id) != claims.subject
            ):
                raise InvalidTokenError()

            user = await self.repo.get_user(stored.user_id)
            if user is None or user.status != UserStatus.ACTIVE:
                raise InvalidCredentialsError()

            await self.repo.revoke_refresh_token(stored)
            return await self._issue_token_pair(user)

    async def logout(self, *, user_id: UUID, refresh_token: str) -> None:
        claims = self._decode_refresh(refresh_token)
        async with transaction(self.session):
            stored = await self.repo.get_refresh_token_by_jti(claims.token_id, for_update=True)
            if stored is None:
                return
            if stored.user_id != user_id:
                raise InvalidTokenError()
            await self.repo.revoke_refresh_token(stored)
            await self.audit.write(
                user_id=user_id,
                action=AuditAction.LOGOUT,
                module=IDENTITY_MODULE,
                entity_type="user",
                entity_id=user_id,
            )

    async def logout_all(self, *, user_id: UUID) -> None:
        async with transaction(self.session):
            await self._revoke_all_sessions(user_id)
            await self.audit.write(
                user_id=user_id,
                action=AuditAction.LOGOUT,
                module=IDENTITY_MODULE,
                entity_type="user",
                entity_id=user_id,
                new_values={"logout_all": True},
            )

    async def me(self, *, user_id: UUID) -> MeResponse:
        try:
            async with transaction(self.session):
                await self._ensure_catalog()
        except IntegrityError:
            await self.session.rollback()
        user = await self._require_user(user_id)
        detail = await self._user_detail(user)
        permissions = await self.repo.list_user_permission_strings(user_id)
        return MeResponse(**detail.model_dump(), permissions=sorted(permissions))

    async def update_me(self, *, user_id: UUID, payload: MeUpdate) -> MeResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            user = await self._require_user(user_id)
            old_values = await self._user_snapshot(user)
            for name, value in values.items():
                setattr(user, name, value)
            await self.session.flush()
            new_values = await self._user_snapshot(user)
            if audit_field_changes(old_values, new_values):
                await self.audit.write(
                    user_id=user_id,
                    action=AuditAction.UPDATE,
                    module=IDENTITY_MODULE,
                    entity_type="user",
                    entity_id=user.id,
                    old_values=old_values,
                    new_values=new_values,
                )
        return await self.me(user_id=user_id)

    async def change_password(
        self,
        *,
        user_id: UUID,
        payload: ChangePasswordRequest,
    ) -> TokenPairResponse:
        new_hash = self._hash_password(payload.new_password)
        async with transaction(self.session):
            user = await self._require_user(user_id)
            if user.password_hash is None or not verify_password(
                payload.current_password,
                user.password_hash,
            ):
                raise InvalidCredentialsError()
            user.password_hash = new_hash
            await self._revoke_all_sessions(user_id)
            await self.audit.write(
                user_id=user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="user",
                entity_id=user.id,
                new_values={"password_changed": True},
            )
            return await self._issue_token_pair(user)

    async def request_password_reset(self, payload: ForgotPasswordRequest) -> ForgotPasswordResponse:
        settings = get_settings()
        generic = ForgotPasswordResponse(
            message=(
                "If an account exists for that email, password reset instructions have been sent."
            )
        )
        raw_token: str | None = None
        async with transaction(self.session):
            user = await self.repo.get_user_by_email(payload.email)
            if (
                user is not None
                and user.status == UserStatus.ACTIVE
                and user.password_hash is not None
            ):
                raw_token = generate_password_reset_token()
                token_hash = hash_password_reset_token(
                    raw_token, secret=settings.jwt_secret.get_secret_value()
                )
                expires_at = utcnow() + timedelta(minutes=settings.password_reset_ttl_minutes)
                await self.repo.create_password_reset_token(
                    user_id=user.id,
                    token_hash=token_hash,
                    expires_at=expires_at,
                )
                await self.audit.write(
                    user_id=user.id,
                    action=AuditAction.UPDATE,
                    module=IDENTITY_MODULE,
                    entity_type="user",
                    entity_id=user.id,
                    new_values={"password_reset_requested": True},
                )
        if settings.env == "testing" and raw_token is not None:
            return ForgotPasswordResponse(message=generic.message, reset_token=raw_token)
        return generic

    async def reset_password(self, payload: ResetPasswordRequest) -> None:
        settings = get_settings()
        token_hash = hash_password_reset_token(
            payload.token.strip(), secret=settings.jwt_secret.get_secret_value()
        )
        new_hash = self._hash_password(payload.new_password)
        async with transaction(self.session):
            stored = await self.repo.get_password_reset_token(token_hash, for_update=True)
            if stored is None or stored.used_at is not None or stored.expires_at <= utcnow():
                raise InvalidTokenError("Invalid or expired password reset token")
            user = await self.repo.get_user(stored.user_id)
            if user is None or user.status != UserStatus.ACTIVE:
                raise InvalidTokenError("Invalid or expired password reset token")
            user.password_hash = new_hash
            stored.used_at = utcnow()
            await self._revoke_all_sessions(user.id)
            await self.audit.write(
                user_id=user.id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="user",
                entity_id=user.id,
                new_values={"password_reset": True},
            )

    async def list_users(
        self,
        *,
        page: PageParams,
        user_filter: UserFilter,
    ) -> tuple[list[UserResponse], int]:
        status = user_filter.status.value if user_filter.status is not None else None
        filters = {"status": status} if status is not None else None
        users, total = await self.repo.list_users(
            page=page,
            common_filter=user_filter,
            filters=filters,
            user_filter=user_filter,
        )
        user_list = list(users)
        roles_by_user = await self.repo.list_roles_for_users([user.id for user in user_list])
        responses = [await self._to_user_response(user, roles=roles_by_user.get(user.id, [])) for user in user_list]
        return responses, total

    async def create_user(
        self,
        payload: UserCreate,
        *,
        actor_user_id: UUID,
    ) -> UserDetailResponse:
        password_hash = self._hash_password(payload.password)
        async with transaction(self.session):
            await self._validate_branch_department(payload.branch_id, payload.department_id)
            try:
                user = await self.repo.create_user(
                    {
                        "name": payload.name,
                        "email": payload.email,
                        "password_hash": password_hash,
                        "phone": payload.phone,
                        "status": payload.status.value,
                        "branch_id": payload.branch_id,
                        "department_id": payload.department_id,
                        "designation": payload.designation,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A user with this email already exists") from exc
            await self._validate_role_assignment(
                user,
                payload.role_ids,
                actor_user_id=actor_user_id,
                old_roles=(),
            )
            await self._replace_user_roles(user.id, payload.role_ids)
            roles = await self.repo.list_user_roles(user.id)
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=IDENTITY_MODULE,
                entity_type="user",
                entity_id=user.id,
                new_values=await self._user_snapshot(user, roles=roles),
            )
            return await self._user_detail(user)

    async def get_user(self, user_id: UUID) -> UserDetailResponse:
        user = await self._require_user(user_id)
        return await self._user_detail(user)

    async def update_user(
        self,
        user_id: UUID,
        payload: UserUpdate,
        *,
        actor_user_id: UUID,
    ) -> UserDetailResponse:
        values = payload.model_dump(exclude_unset=True)
        status = values.get("status")
        if status == UserStatus.DISABLED and user_id == actor_user_id:
            raise ValidationError("You cannot deactivate your own account")
        if status is not None:
            values["status"] = str(status)

        async with transaction(self.session):
            user = await self._require_user(user_id)
            if status == UserStatus.DISABLED:
                await self._ensure_not_last_active_superadmin(user)
            await self._validate_branch_department(
                values.get("branch_id", user.branch_id),
                values.get("department_id", user.department_id),
            )
            old_values = await self._user_snapshot(user)
            for name, value in values.items():
                setattr(user, name, value)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise DuplicateResourceError("A user with this email already exists") from exc
            if status == UserStatus.DISABLED:
                await self._revoke_all_sessions(user_id)
            new_values = await self._user_snapshot(user)
            if audit_field_changes(old_values, new_values):
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=IDENTITY_MODULE,
                    entity_type="user",
                    entity_id=user.id,
                    old_values=old_values,
                    new_values=new_values,
                )
            return await self._user_detail(user)

    async def deactivate_user(self, user_id: UUID, *, actor_user_id: UUID) -> UserDetailResponse:
        if user_id == actor_user_id:
            raise ValidationError("You cannot deactivate your own account")
        async with transaction(self.session):
            user = await self._require_user(user_id)
            await self._ensure_not_last_active_superadmin(user)
            old_status = user.status
            user.status = UserStatus.DISABLED
            await self._revoke_all_sessions(user_id)
            await self.session.flush()
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="user",
                entity_id=user.id,
                old_values={"status": old_status},
                new_values={"status": user.status},
            )
            return await self._user_detail(user)

    async def activate_user(self, user_id: UUID, *, actor_user_id: UUID) -> UserDetailResponse:
        async with transaction(self.session):
            user = await self._require_user(user_id)
            if user.status != UserStatus.DISABLED:
                raise InvalidStatusTransitionError("Only disabled users can be activated")
            old_status = user.status
            user.status = UserStatus.ACTIVE
            await self.session.flush()
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="user",
                entity_id=user.id,
                old_values={"status": old_status},
                new_values={"status": user.status},
            )
            return await self._user_detail(user)

    async def admin_reset_user_password(
        self,
        user_id: UUID,
        payload: AdminResetUserPasswordRequest,
        *,
        actor_user_id: UUID,
    ) -> UserDetailResponse:
        if user_id == actor_user_id:
            raise ValidationError("Use change password to reset your own password")
        new_hash = self._hash_password(payload.new_password)
        async with transaction(self.session):
            user = await self._require_user(user_id)
            user.password_hash = new_hash
            await self._revoke_all_sessions(user_id)
            await self.session.flush()
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="user",
                entity_id=user.id,
                new_values={"password_reset_by_admin": True},
            )
            return await self._user_detail(user)

    async def assign_roles(
        self,
        user_id: UUID,
        payload: AssignRolesRequest,
        *,
        actor_user_id: UUID,
    ) -> UserDetailResponse:
        async with transaction(self.session):
            user = await self._require_user(user_id)
            old_roles = await self.repo.list_user_roles(user.id)
            await self._validate_role_assignment(
                user,
                payload.role_ids,
                actor_user_id=actor_user_id,
                old_roles=old_roles,
            )
            await self._replace_user_roles(user.id, payload.role_ids)
            new_roles = await self.repo.list_user_roles(user.id)
            old_values: dict[str, object] = {"roles": _role_names(old_roles)}
            new_values: dict[str, object] = {"roles": _role_names(new_roles)}
            if audit_field_changes(old_values, new_values):
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=IDENTITY_MODULE,
                    entity_type="user",
                    entity_id=user.id,
                    old_values=old_values,
                    new_values=new_values,
                )
            return await self._user_detail(user)

    async def list_roles(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
    ) -> tuple[list[RoleResponse], int]:
        roles, total = await self.repo.list_roles(page=page, common_filter=common_filter)
        role_list = list(roles)
        counts = await self.repo.count_users_by_role_ids([role.id for role in role_list])
        return [
            RoleResponse.model_validate(role).model_copy(
                update={"user_count": counts.get(role.id, 0)}
            )
            for role in role_list
        ], total

    async def create_role(
        self,
        payload: RoleCreate,
        *,
        actor_user_id: UUID,
        actor_permissions: frozenset[str],
    ) -> RoleDetailResponse:
        async with transaction(self.session):
            try:
                role = await self.repo.create_role(
                    {
                        "name": payload.name,
                        "description": payload.description,
                        "is_system_role": False,
                        "record_scope": payload.record_scope,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A role with this name already exists") from exc
            await self._replace_role_permissions(
                role.id,
                payload.permission_ids,
                actor_user_id=actor_user_id,
                actor_permissions=actor_permissions,
            )
            permissions = await self.repo.list_role_permissions(role.id)
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=IDENTITY_MODULE,
                entity_type="role",
                entity_id=role.id,
                new_values={**_role_snapshot(role), "permissions": _permission_codes(permissions)},
            )
            return await self._role_detail(role)

    async def get_role(self, role_id: UUID) -> RoleDetailResponse:
        role = await self._require_role(role_id)
        return await self._role_detail(role)

    async def update_role(
        self,
        role_id: UUID,
        payload: RoleUpdate,
        *,
        actor_user_id: UUID,
    ) -> RoleDetailResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            role = await self._require_role(role_id)
            if role.is_system_role and "name" in values and values["name"] != role.name:
                raise ValidationError("System role names cannot be changed")
            old_values = _role_snapshot(role)
            for name, value in values.items():
                setattr(role, name, value)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise DuplicateResourceError("A role with this name already exists") from exc
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="role",
                entity_id=role.id,
                old_values=old_values,
                new_values=_role_snapshot(role),
            )
            return await self._role_detail(role)

    async def delete_role(self, role_id: UUID, *, actor_user_id: UUID) -> RoleResponse:
        async with transaction(self.session):
            role = await self._require_role(role_id)
            if role.is_system_role:
                raise ValidationError("System roles cannot be deleted")
            counts = await self.repo.count_users_by_role_ids([role.id])
            if counts.get(role.id, 0) > 0:
                raise ValidationError("Cannot delete a role that is assigned to users")
            response = RoleResponse.model_validate(role).model_copy(
                update={"user_count": counts.get(role.id, 0)}
            )
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=IDENTITY_MODULE,
                entity_type="role",
                entity_id=role.id,
                old_values=_role_snapshot(role),
            )
            await self.repo.delete_role(role)
        return response

    async def set_role_permissions(
        self,
        role_id: UUID,
        payload: SetRolePermissionsRequest,
        *,
        actor_user_id: UUID,
        actor_permissions: frozenset[str],
    ) -> RoleDetailResponse:
        async with transaction(self.session):
            role = await self._require_role(role_id)
            if self._is_system_admin_role(role):
                raise ValidationError(
                    "Superadmin permissions cannot be edited manually; reset them to the catalog"
                )
            old_permissions = await self.repo.list_role_permissions(role.id)
            await self._replace_role_permissions(
                role.id,
                payload.permission_ids,
                actor_user_id=actor_user_id,
                actor_permissions=actor_permissions,
            )
            new_permissions = await self.repo.list_role_permissions(role.id)
            old_values: dict[str, object] = {"permissions": _permission_codes(old_permissions)}
            new_values: dict[str, object] = {"permissions": _permission_codes(new_permissions)}
            if audit_field_changes(old_values, new_values):
                await self.audit.write(
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=IDENTITY_MODULE,
                    entity_type="role",
                    entity_id=role.id,
                    old_values=old_values,
                    new_values=new_values,
                )
            return await self._role_detail(role)

    async def reset_role_permissions(self, role_id: UUID, *, actor_user_id: UUID) -> RoleDetailResponse:
        async with transaction(self.session):
            role = await self._require_role(role_id)
            if not role.is_system_role or role.name != SYSTEM_ADMIN_ROLE_NAME:
                raise ValidationError("Only the system Superadmin role can be reset to the catalog")
            if not await self._actor_is_system_admin(actor_user_id):
                raise ValidationError("Only a Superadmin can reset Superadmin permissions")
            await seed_permissions(self.session)
            permissions = await self.repo.list_all_permissions()
            await self.repo.replace_role_permissions(role.id, [item.id for item in permissions])
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="role",
                entity_id=role.id,
                new_values={"permissions_reset": True},
            )
            return await self._role_detail(role)

    async def list_permissions(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        module: str | None = None,
    ) -> tuple[list[PermissionResponse], int]:
        filters = {"module": module} if module is not None else None
        permissions, total = await self.repo.list_permissions(
            page=page,
            common_filter=common_filter,
            filters=filters,
        )
        return [PermissionResponse.model_validate(item) for item in permissions], total

    async def permission_matrix(self, *, role_id: UUID | None = None) -> PermissionMatrixResponse:
        try:
            async with transaction(self.session):
                await self._ensure_catalog()
        except IntegrityError:
            await self.session.rollback()

        granted_ids: set[UUID] = set()
        if role_id is not None:
            role = await self._require_role(role_id)
            granted = await self.repo.list_role_permissions(role.id)
            granted_ids = {item.id for item in granted}

        catalog = await self.repo.list_all_permissions()
        modules: dict[str, dict[str, list[PermissionMatrixAction]]] = {}
        for item in catalog:
            code = build_permission(item.module, item.resource, item.action)
            modules.setdefault(item.module, {}).setdefault(item.resource, []).append(
                PermissionMatrixAction(
                    id=item.id,
                    action=item.action,
                    code=code,
                    granted=item.id in granted_ids,
                )
            )
        return PermissionMatrixResponse(
            modules=[
                PermissionMatrixModule(
                    module=module_name,
                    resources=[
                        PermissionMatrixResource(resource=resource_name, actions=actions)
                        for resource_name, actions in resources.items()
                    ],
                )
                for module_name, resources in modules.items()
            ]
        )

    async def _validate_branch_department(
        self,
        branch_id: UUID | None,
        department_id: UUID | None,
    ) -> None:
        if branch_id is not None and await self.org.get_branch(branch_id) is None:
            raise ResourceNotFoundError("Branch not found")
        if department_id is not None:
            department = await self.org.get_department(department_id)
            if department is None:
                raise ResourceNotFoundError("Department not found")
            if branch_id is not None and department.branch_id != branch_id:
                raise ValidationError("Department does not belong to the selected branch")

    async def _user_snapshot(
        self, user: User, *, roles: Sequence[Role] | None = None
    ) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "name": user.name,
            "email": user.email,
            "phone": user.phone,
            "status": user.status,
            "designation": user.designation,
            "branch_id": str(user.branch_id) if user.branch_id else None,
            "department_id": str(user.department_id) if user.department_id else None,
        }
        if roles is not None:
            snapshot["roles"] = _role_names(roles)
        return snapshot

    async def _require_user(self, user_id: UUID) -> User:
        user = await self.repo.get_user(user_id)
        if user is None:
            raise ResourceNotFoundError("User not found")
        return user

    async def _require_role(self, role_id: UUID) -> Role:
        role = await self.repo.get_role(role_id)
        if role is None:
            raise ResourceNotFoundError("Role not found")
        return role

    async def _user_detail(self, user: User) -> UserDetailResponse:
        await self.session.refresh(user)
        roles = await self.repo.list_user_roles(user.id)
        return UserDetailResponse.model_validate(
            await self._to_user_response(user, roles=list(roles))
        )

    async def _to_user_response(self, user: User, *, roles: Sequence[Role]) -> UserResponse:
        branch = None
        department = None
        if user.branch_id is not None:
            branches = await self.org.get_branches_by_ids([user.branch_id])
            if user.branch_id in branches:
                branch = BranchSummary.model_validate(branches[user.branch_id])
        if user.department_id is not None:
            departments = await self.org.get_departments_by_ids([user.department_id])
            if user.department_id in departments:
                department = DepartmentSummary.model_validate(departments[user.department_id])
        return UserResponse.model_validate(user).model_copy(
            update={
                "roles": [RoleSummary.model_validate(role) for role in roles],
                "branch": branch,
                "department": department,
            }
        )

    async def _role_detail(self, role: Role) -> RoleDetailResponse:
        await self.session.refresh(role)
        permissions = await self.repo.list_role_permissions(role.id)
        counts = await self.repo.count_users_by_role_ids([role.id])
        return RoleDetailResponse(
            **RoleResponse.model_validate(role)
            .model_copy(update={"user_count": counts.get(role.id, 0)})
            .model_dump(),
            permissions=[PermissionResponse.model_validate(item) for item in permissions],
        )

    async def _replace_user_roles(self, user_id: UUID, role_ids: Sequence[UUID]) -> None:
        unique_ids = list(dict.fromkeys(role_ids))
        roles = await self.repo.get_roles_by_ids(unique_ids)
        if len(roles) != len(unique_ids):
            raise ResourceNotFoundError("Role not found")
        await self.repo.replace_user_roles(user_id, unique_ids)

    def _is_system_admin_role(self, role: Role) -> bool:
        return role.is_system_role and role.name == SYSTEM_ADMIN_ROLE_NAME

    async def _actor_is_system_admin(self, actor_user_id: UUID) -> bool:
        roles = await self.repo.list_user_roles(actor_user_id)
        return any(self._is_system_admin_role(role) for role in roles)

    async def _ensure_not_last_active_superadmin(self, user: User) -> None:
        if user.status != UserStatus.ACTIVE:
            return
        roles = await self.repo.list_user_roles(user.id)
        if not any(self._is_system_admin_role(role) for role in roles):
            return
        if await self.repo.count_active_system_admins() <= 1:
            raise ValidationError("Cannot remove or disable the last active Superadmin")

    async def _validate_role_assignment(
        self,
        user: User,
        role_ids: Sequence[UUID],
        *,
        actor_user_id: UUID,
        old_roles: Sequence[Role],
    ) -> None:
        if user.id == actor_user_id:
            raise ValidationError("You cannot change your own role assignments")
        unique_ids = list(dict.fromkeys(role_ids))
        new_roles = await self.repo.get_roles_by_ids(unique_ids)
        if len(new_roles) != len(unique_ids):
            raise ResourceNotFoundError("Role not found")
        new_has_admin = any(self._is_system_admin_role(role) for role in new_roles)
        old_has_admin = any(self._is_system_admin_role(role) for role in old_roles)
        actor_is_admin = await self._actor_is_system_admin(actor_user_id)
        if new_has_admin and not actor_is_admin:
            raise ValidationError("Only a Superadmin can assign the Superadmin role")
        if (
            old_has_admin
            and not new_has_admin
            and user.status == UserStatus.ACTIVE
            and await self.repo.count_active_system_admins() <= 1
        ):
            raise ValidationError("Cannot remove or disable the last active Superadmin")

    async def _ensure_catalog(self) -> None:
        admin = await get_system_admin_role(self.session)
        if admin is not None:
            await grant_catalog_to_role(self.session, admin.id)
            return
        await ensure_superadmin(self.session)

    async def _replace_role_permissions(
        self,
        role_id: UUID,
        permission_ids: Sequence[UUID],
        *,
        actor_user_id: UUID,
        actor_permissions: frozenset[str],
    ) -> None:
        unique_ids = list(dict.fromkeys(permission_ids))
        permissions = await self.repo.get_permissions_by_ids(unique_ids)
        if len(permissions) != len(unique_ids):
            raise ResourceNotFoundError("Permission not found")
        actor_is_superadmin = await self._actor_is_system_admin(actor_user_id)
        granted_codes = {
            build_permission(permission.module, permission.resource, permission.action)
            for permission in permissions
        }
        validate_permission_grant_subset(
            granted_codes,
            actor_permissions,
            actor_is_superadmin=actor_is_superadmin,
        )
        await self.repo.replace_role_permissions(role_id, unique_ids)

    async def _revoke_all_sessions(self, user_id: UUID) -> None:
        await self.repo.bump_token_version(user_id)
        await self.repo.revoke_user_refresh_tokens(user_id)

    def _decode_refresh(self, refresh_token: str) -> TokenClaims:
        settings = get_settings()
        return decode_refresh_token(
            refresh_token,
            secret=settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )

    def _hash_password(self, password: str) -> str:
        try:
            return hash_password(password)
        except PasswordTooLongError as exc:
            raise ValidationError("Password exceeds bcrypt's 72-byte UTF-8 limit") from exc

    async def _issue_token_pair(self, user: User) -> TokenPairResponse:
        settings = get_settings()
        secret = settings.jwt_secret.get_secret_value()
        algorithm = settings.jwt_algorithm
        access_delta = timedelta(minutes=settings.jwt_access_token_ttl_minutes)
        refresh_delta = timedelta(minutes=settings.jwt_refresh_token_ttl_minutes)
        subject = str(user.id)

        access_token = create_access_token(
            subject=subject,
            secret=secret,
            expires_delta=access_delta,
            tenant_id=None,
            algorithm=algorithm,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            token_version=user.token_version,
        )
        refresh_token = create_refresh_token(
            subject=subject,
            secret=secret,
            expires_delta=refresh_delta,
            tenant_id=None,
            algorithm=algorithm,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
        refresh_claims = decode_refresh_token(
            refresh_token,
            secret=secret,
            algorithm=algorithm,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
        await self.repo.create_refresh_token(
            user_id=user.id,
            jti=refresh_claims.token_id,
            expires_at=refresh_claims.expires_at,
        )
        return TokenPairResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int(access_delta.total_seconds()),
        )
