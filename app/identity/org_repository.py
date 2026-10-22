"""Database access for addresses, branches, departments, and organization."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.repositories.search import address_search, branch_search, user_search
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.core.enums import AddressType
from app.identity.models import Address, Branch, Department, User


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.addresses = BaseRepository(
            session,
            Address,
            allowed_sort_fields=frozenset({"created_at", "updated_at"}),
        )
        self.branches = BaseRepository(
            session,
            Branch,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name", "code", "status"}),
            allowed_filter_fields=frozenset({"status"}),
            search_fields=frozenset({"name", "code", "phone"}),
            related_searches=(address_search("address_id"),),
        )
        self.departments = BaseRepository(
            session,
            Department,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name", "code"}),
            allowed_filter_fields=frozenset({"branch_id"}),
            search_fields=frozenset({"name", "code"}),
            related_searches=(branch_search(), user_search("manager_id")),
        )

    async def get_address(self, address_id: UUID) -> Address | None:
        return await self.addresses.get(address_id)

    async def get_addresses(self, address_ids: Sequence[UUID]) -> dict[UUID, Address]:
        unique = list(dict.fromkeys(address_ids))
        if not unique:
            return {}
        result = await self.session.execute(
            select(Address).where(Address.id.in_(unique), Address.deleted_at.is_(None))
        )
        return {row.id: row for row in result.scalars().all()}

    async def create_address(
        self,
        values: Mapping[str, object],
        *,
        address_type: AddressType = AddressType.BRANCH,
    ) -> Address:
        payload = dict(values)
        payload.setdefault("address_type", address_type.value)
        return await self.addresses.create(payload)

    async def update_address(self, address_id: UUID, values: Mapping[str, object]) -> Address | None:
        return await self.addresses.update(address_id, values)

    async def get_branch(self, branch_id: UUID) -> Branch | None:
        return await self.branches.get(branch_id)

    async def get_branches_by_ids(self, branch_ids: Sequence[UUID]) -> dict[UUID, Branch]:
        unique = list(dict.fromkeys(branch_ids))
        if not unique:
            return {}
        result = await self.session.execute(
            select(Branch).where(Branch.id.in_(unique), Branch.deleted_at.is_(None))
        )
        return {row.id: row for row in result.scalars().all()}

    async def list_branches(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Branch], int]:
        return await self.branches.list(page=page, common_filter=common_filter, filters=filters)

    async def create_branch(self, values: Mapping[str, object]) -> Branch:
        return await self.branches.create(values)

    async def update_branch(self, branch_id: UUID, values: Mapping[str, object]) -> Branch | None:
        return await self.branches.update(branch_id, values)

    async def soft_delete_branch(self, branch_id: UUID) -> Branch | None:
        return await self.branches.soft_delete(branch_id)

    async def get_department(self, department_id: UUID) -> Department | None:
        return await self.departments.get(department_id)

    async def get_departments_by_ids(self, department_ids: Sequence[UUID]) -> dict[UUID, Department]:
        unique = list(dict.fromkeys(department_ids))
        if not unique:
            return {}
        result = await self.session.execute(
            select(Department).where(Department.id.in_(unique), Department.deleted_at.is_(None))
        )
        return {row.id: row for row in result.scalars().all()}

    async def list_departments(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Department], int]:
        return await self.departments.list(page=page, common_filter=common_filter, filters=filters)

    async def create_department(self, values: Mapping[str, object]) -> Department:
        return await self.departments.create(values)

    async def update_department(
        self, department_id: UUID, values: Mapping[str, object]
    ) -> Department | None:
        return await self.departments.update(department_id, values)

    async def soft_delete_department(self, department_id: UUID) -> Department | None:
        return await self.departments.soft_delete(department_id)

    async def get_users_by_ids(self, user_ids: Sequence[UUID]) -> dict[UUID, User]:
        unique = list(dict.fromkeys(user_ids))
        if not unique:
            return {}
        result = await self.session.execute(select(User).where(User.id.in_(unique)))
        return {row.id: row for row in result.scalars().all()}

    async def count_departments_for_branch(self, branch_id: UUID) -> int:
        total = await self.session.scalar(
            select(func.count())
            .select_from(Department)
            .where(Department.branch_id == branch_id, Department.deleted_at.is_(None))
        )
        return int(total or 0)

    async def count_users_for_branch(self, branch_id: UUID) -> int:
        total = await self.session.scalar(
            select(func.count()).select_from(User).where(User.branch_id == branch_id)
        )
        return int(total or 0)

    async def count_users_for_department(self, department_id: UUID) -> int:
        total = await self.session.scalar(
            select(func.count()).select_from(User).where(User.department_id == department_id)
        )
        return int(total or 0)

    async def count_users(self) -> int:
        total = await self.session.scalar(select(func.count()).select_from(User))
        return int(total or 0)

    async def count_branches(self) -> int:
        total = await self.session.scalar(
            select(func.count()).select_from(Branch).where(Branch.deleted_at.is_(None))
        )
        return int(total or 0)

    async def count_departments(self) -> int:
        total = await self.session.scalar(
            select(func.count()).select_from(Department).where(Department.deleted_at.is_(None))
        )
        return int(total or 0)
