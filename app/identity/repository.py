"""Database access for users, roles, permissions, warehouses, and refresh tokens."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.search import RelatedSearch, USER_FIELDS, search_clause
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.utils.time import utcnow
from app.core.enums import SYSTEM_ADMIN_ROLE_NAME, UserStatus
from app.core.permissions import build_permission
from app.db.base import Base
from app.identity.models import (
    Department,
    Organization,
    PasswordResetToken,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    User,
    UserRole,
    Warehouse,
)
from app.identity.schemas import UserFilter


class AccessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _column(model: type[Base], name: str) -> InstrumentedAttribute[Any]:
        column = getattr(model, name, None)
        if not isinstance(column, InstrumentedAttribute):
            msg = f"{model.__name__} has no mapped column {name!r}"
            raise TypeError(msg)
        return column

    def _list_criteria(
        self,
        model: type[Base],
        *,
        filters: Mapping[str, object] | None = None,
        common_filter: BaseFilter | None = None,
        search_fields: frozenset[str] = frozenset(),
        allowed_filter_fields: frozenset[str] = frozenset(),
        extra_criteria: Sequence[ColumnElement[bool]] = (),
        related_searches: Sequence[RelatedSearch] = (),
    ) -> list[ColumnElement[bool]]:
        criteria: list[ColumnElement[bool]] = []
        deleted = getattr(model, "deleted_at", None)
        if isinstance(deleted, InstrumentedAttribute):
            criteria.append(deleted.is_(None))

        if filters:
            unknown = filters.keys() - allowed_filter_fields
            if unknown:
                fields = ", ".join(sorted(unknown))
                raise ValueError(f"filter fields are not allowed: {fields}")
            criteria.extend(self._column(model, name) == value for name, value in filters.items())

        if common_filter is not None:
            if common_filter.date_from is not None:
                criteria.append(self._column(model, "created_at") >= common_filter.date_from)
            if common_filter.date_to is not None:
                criteria.append(self._column(model, "created_at") <= common_filter.date_to)
            if common_filter.search is not None:
                criteria.append(
                    search_clause(
                        model,
                        tenant_id=UUID(int=0),
                        search=common_filter.search,
                        fields=search_fields,
                        related=related_searches,
                    )
                )

        criteria.extend(extra_criteria)
        return criteria

    def _apply_sort(
        self,
        model: type[Base],
        statement: Select[tuple[Any]],
        *,
        common_filter: BaseFilter | None,
        allowed_sort_fields: frozenset[str],
    ) -> Select[tuple[Any]]:
        sort_by = common_filter.sort_by if common_filter else "created_at"
        sort_order = common_filter.sort_order if common_filter else "desc"
        if sort_by not in allowed_sort_fields:
            raise ValueError(f"sort field is not allowed: {sort_by}")
        sort_column = self._column(model, sort_by)
        ordering = sort_column.desc() if sort_order == "desc" else sort_column.asc()
        return statement.order_by(ordering)

    async def _paginated[ModelT: Base](
        self,
        model: type[ModelT],
        *,
        page: PageParams,
        common_filter: BaseFilter | None,
        filters: Mapping[str, object] | None,
        search_fields: frozenset[str],
        allowed_filter_fields: frozenset[str],
        allowed_sort_fields: frozenset[str],
        extra_criteria: Sequence[ColumnElement[bool]] = (),
        related_searches: Sequence[RelatedSearch] = (),
    ) -> tuple[Sequence[ModelT], int]:
        criteria = self._list_criteria(
            model,
            filters=filters,
            common_filter=common_filter,
            search_fields=search_fields,
            allowed_filter_fields=allowed_filter_fields,
            extra_criteria=extra_criteria,
            related_searches=related_searches,
        )
        statement = self._apply_sort(
            model,
            select(model).where(*criteria),
            common_filter=common_filter,
            allowed_sort_fields=allowed_sort_fields,
        )
        statement = statement.offset(page.offset).limit(page.page_size)
        count_statement = select(func.count()).select_from(model).where(*criteria)
        result = await self.session.execute(statement)
        total = await self.session.scalar(count_statement)
        return result.scalars().all(), int(total or 0)

    async def get_organization(self, *, for_update: bool = False) -> Organization | None:
        statement = select(Organization).limit(1)
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_user(self, user_id: UUID) -> User | None:
        return await self.get_user_by_id(user_id)

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    def _user_list_extra_criteria(self, user_filter: UserFilter | None) -> list[ColumnElement[bool]]:
        if user_filter is None:
            return []
        extra: list[ColumnElement[bool]] = []
        role_ids = user_filter.collected_role_ids()
        if role_ids:
            extra.append(
                User.id.in_(select(UserRole.user_id).where(UserRole.role_id.in_(role_ids)))
            )
        if user_filter.phone is not None:
            extra.append(User.phone.ilike(f"%{user_filter.phone}%"))
        if user_filter.last_login_from is not None:
            extra.append(User.last_login_at >= user_filter.last_login_from)
        if user_filter.last_login_to is not None:
            extra.append(User.last_login_at <= user_filter.last_login_to)
        if user_filter.branch_id is not None:
            extra.append(User.branch_id == user_filter.branch_id)
        if user_filter.department_id is not None:
            extra.append(User.department_id == user_filter.department_id)
        if user_filter.designation is not None:
            extra.append(User.designation.ilike(f"%{user_filter.designation}%"))
        return extra

    async def list_users(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
        user_filter: UserFilter | None = None,
    ) -> tuple[Sequence[User], int]:
        return await self._paginated(
            User,
            page=page,
            common_filter=common_filter,
            filters=filters,
            search_fields=USER_FIELDS,
            allowed_filter_fields=frozenset({"status"}),
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "name", "email", "status", "last_login_at"}
            ),
            extra_criteria=self._user_list_extra_criteria(user_filter),
        )

    async def create_user(self, values: Mapping[str, object]) -> User:
        user = User()
        for name, value in values.items():
            setattr(user, name, value)
        self.session.add(user)
        await self.session.flush()
        return user

    async def list_user_record_scopes(self, user_id: UUID) -> Sequence[str]:
        statement = (
            select(Role.record_scope)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        result = await self.session.execute(statement)
        return [row[0] for row in result.all()]

    async def list_user_permission_strings(self, user_id: UUID) -> frozenset[str]:
        statement = (
            select(Permission.module, Permission.resource, Permission.action)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
            .distinct()
        )
        result = await self.session.execute(statement)
        return frozenset(
            build_permission(row.module, row.resource, row.action) for row in result.all()
        )

    async def list_user_roles(self, user_id: UUID) -> Sequence[Role]:
        statement = (
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .order_by(Role.name.asc())
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def list_roles_for_users(self, user_ids: Sequence[UUID]) -> dict[UUID, list[Role]]:
        if not user_ids:
            return {}
        statement = (
            select(UserRole.user_id, Role)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(list(user_ids)))
            .order_by(Role.name.asc())
        )
        result = await self.session.execute(statement)
        grouped: dict[UUID, list[Role]] = {}
        for user_id, role in result.all():
            grouped.setdefault(user_id, []).append(role)
        return grouped

    async def get_roles_by_ids(self, role_ids: Sequence[UUID]) -> Sequence[Role]:
        if not role_ids:
            return []
        result = await self.session.execute(select(Role).where(Role.id.in_(role_ids)))
        return result.scalars().all()

    async def replace_user_roles(self, user_id: UUID, role_ids: Sequence[UUID]) -> None:
        await self.session.execute(delete(UserRole).where(UserRole.user_id == user_id))
        await self.session.flush()
        for role_id in role_ids:
            self.session.add(UserRole(user_id=user_id, role_id=role_id))
        await self.session.flush()

    async def get_role(self, role_id: UUID) -> Role | None:
        result = await self.session.execute(select(Role).where(Role.id == role_id))
        return result.scalar_one_or_none()

    async def list_roles(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
    ) -> tuple[Sequence[Role], int]:
        return await self._paginated(
            Role,
            page=page,
            common_filter=common_filter,
            filters=None,
            search_fields=frozenset({"name", "description"}),
            allowed_filter_fields=frozenset(),
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name"}),
        )

    async def create_role(self, values: Mapping[str, object]) -> Role:
        role = Role()
        for name, value in values.items():
            setattr(role, name, value)
        self.session.add(role)
        await self.session.flush()
        return role

    async def delete_role(self, role: Role) -> None:
        await self.session.delete(role)
        await self.session.flush()

    async def get_permissions_by_ids(self, permission_ids: Sequence[UUID]) -> Sequence[Permission]:
        if not permission_ids:
            return []
        result = await self.session.execute(
            select(Permission).where(Permission.id.in_(permission_ids))
        )
        return result.scalars().all()

    async def list_role_permissions(self, role_id: UUID) -> Sequence[Permission]:
        statement = (
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
            .order_by(Permission.module.asc(), Permission.resource.asc(), Permission.action.asc())
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def replace_role_permissions(self, role_id: UUID, permission_ids: Sequence[UUID]) -> None:
        await self.session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
        await self.session.flush()
        for permission_id in permission_ids:
            self.session.add(RolePermission(role_id=role_id, permission_id=permission_id))
        await self.session.flush()

    async def list_permissions(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Permission], int]:
        return await self._paginated(
            Permission,
            page=page,
            common_filter=common_filter,
            filters=filters,
            search_fields=frozenset({"module", "resource", "action"}),
            allowed_filter_fields=frozenset({"module"}),
            allowed_sort_fields=frozenset({"created_at", "module", "resource", "action"}),
        )

    async def list_all_permissions(self) -> Sequence[Permission]:
        statement = select(Permission).order_by(
            Permission.module.asc(),
            Permission.resource.asc(),
            Permission.action.asc(),
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def create_refresh_token(
        self,
        *,
        user_id: UUID,
        jti: str,
        expires_at: datetime,
    ) -> RefreshToken:
        token = RefreshToken(user_id=user_id, jti=jti, expires_at=expires_at)
        self.session.add(token)
        await self.session.flush()
        return token

    async def get_refresh_token_by_jti(self, jti: str, *, for_update: bool = False) -> RefreshToken | None:
        statement = select(RefreshToken).where(RefreshToken.jti == jti)
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def revoke_refresh_token(self, token: RefreshToken) -> None:
        if token.revoked_at is None:
            token.revoked_at = utcnow()
            await self.session.flush()

    async def revoke_user_refresh_tokens(self, user_id: UUID) -> None:
        result = await self.session.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
        )
        for token in result.scalars().all():
            token.revoked_at = utcnow()
        await self.session.flush()

    async def bump_token_version(self, user_id: UUID) -> None:
        user = await self.get_user(user_id)
        if user is None:
            return
        user.token_version += 1
        await self.session.flush()

    async def create_password_reset_token(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> PasswordResetToken:
        await self.invalidate_password_reset_tokens(user_id)
        row = PasswordResetToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self.session.add(row)
        await self.session.flush()
        return row

    async def invalidate_password_reset_tokens(self, user_id: UUID) -> None:
        result = await self.session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
            )
        )
        for row in result.scalars().all():
            row.used_at = utcnow()
        await self.session.flush()

    async def get_password_reset_token(
        self, token_hash: str, *, for_update: bool = False
    ) -> PasswordResetToken | None:
        statement = select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def count_users_by_role_ids(self, role_ids: Sequence[UUID]) -> dict[UUID, int]:
        if not role_ids:
            return {}
        statement = (
            select(UserRole.role_id, func.count())
            .where(UserRole.role_id.in_(list(role_ids)))
            .group_by(UserRole.role_id)
        )
        result = await self.session.execute(statement)
        return {role_id: int(count) for role_id, count in result.all()}

    async def count_active_system_admins(self) -> int:
        statement = (
            select(func.count())
            .select_from(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                User.status == UserStatus.ACTIVE,
                Role.is_system_role.is_(True),
                Role.name == SYSTEM_ADMIN_ROLE_NAME,
            )
        )
        total = await self.session.scalar(statement)
        return int(total or 0)


class WarehouseRepository:
    def __init__(self, session: AsyncSession) -> None:
        from app.common.repositories.base import BaseRepository
        from app.common.repositories.search import address_search

        self._repo = BaseRepository(
            session,
            Warehouse,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name", "code"}),
            allowed_filter_fields=frozenset({"is_active"}),
            search_fields=frozenset({"code", "name", "phone"}),
            related_searches=(address_search("address_id"),),
        )

    async def get(self, warehouse_id: UUID) -> Warehouse | None:
        return await self._repo.get(warehouse_id)

    async def get_default(self) -> Warehouse | None:
        statement = self._repo.base_query().where(Warehouse.is_default.is_(True))
        result = await self._repo.session.execute(statement)
        return result.scalar_one_or_none()

    async def count(self) -> int:
        total = await self._repo.session.scalar(
            select(func.count()).select_from(Warehouse).where(Warehouse.deleted_at.is_(None))
        )
        return int(total or 0)

    async def list(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Warehouse], int]:
        return await self._repo.list(page=page, common_filter=common_filter, filters=filters)

    async def create(self, values: Mapping[str, object]) -> Warehouse:
        return await self._repo.create(values)

    async def update(self, warehouse_id: UUID, values: Mapping[str, object]) -> Warehouse | None:
        return await self._repo.update(warehouse_id, values)

    async def soft_delete(self, warehouse_id: UUID) -> Warehouse | None:
        return await self._repo.soft_delete(warehouse_id)

    async def clear_other_defaults(self, *, keep_id: UUID | None = None) -> None:
        statement = select(Warehouse).where(
            Warehouse.deleted_at.is_(None),
            Warehouse.is_default.is_(True),
        )
        if keep_id is not None:
            statement = statement.where(Warehouse.id != keep_id)
        result = await self._repo.session.execute(statement)
        for row in result.scalars().all():
            row.is_default = False
        await self._repo.session.flush()
