"""Jobs data access."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.repositories.search import RelatedSearch
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.identity.models import Company
from app.inventory.cylinders.models import (
    Cylinder,
    CylinderColor,
    CylinderPause,
    CylinderReturn,
    CylinderSize,
)


class CylinderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Cylinder,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "cylinder_number", "product_name", "status"}
            ),
            allowed_filter_fields=frozenset({"status", "company_id"}),
            search_fields=frozenset({"cylinder_number", "product_name"}),
            related_searches=(
                RelatedSearch(model=Company, local_key="company_id", fields=frozenset({"name"})),
            ),
        )

    async def list(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: dict[str, object] | None = None,
        extra_criteria: Sequence[object] | None = None,
    ) -> tuple[Sequence[Cylinder], int]:
        return await self._repo.list(
            page=page,
            common_filter=common_filter,
            filters=filters,
            extra_criteria=extra_criteria,
        )

    async def get(self, cylinder_id: UUID) -> Cylinder | None:
        return await self._repo.get(cylinder_id)

    async def create(self, values: dict[str, object]) -> Cylinder:
        return await self._repo.create(values)

    async def update(self, cylinder_id: UUID, values: dict[str, object]) -> Cylinder | None:
        return await self._repo.update(cylinder_id, values)

    async def soft_delete(self, cylinder_id: UUID) -> Cylinder | None:
        return await self._repo.soft_delete(cylinder_id)

    async def next_cylinder_number(self) -> str:
        count = await self.session.scalar(
            select(func.count()).select_from(Cylinder).where(Cylinder.deleted_at.is_(None))
        )
        return f"CYL-{(int(count or 0) + 1):05d}"


class CylinderReturnRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            CylinderReturn,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "return_number"}),
            allowed_filter_fields=frozenset({"company_id", "cylinder_id"}),
            search_fields=frozenset({"return_number"}),
            related_searches=(
                RelatedSearch(model=Company, local_key="company_id", fields=frozenset({"name"})),
            ),
        )

    async def list(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: dict[str, object] | None = None,
    ) -> tuple[Sequence[CylinderReturn], int]:
        return await self._repo.list(page=page, common_filter=common_filter, filters=filters)

    async def get(self, return_id: UUID) -> CylinderReturn | None:
        return await self._repo.get(return_id)

    async def get_by_cylinder(self, cylinder_id: UUID) -> CylinderReturn | None:
        statement = select(CylinderReturn).where(
            CylinderReturn.cylinder_id == cylinder_id,
            CylinderReturn.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def create(self, values: dict[str, object]) -> CylinderReturn:
        return await self._repo.create(values)

    async def update(self, return_id: UUID, values: dict[str, object]) -> CylinderReturn | None:
        return await self._repo.update(return_id, values)

    async def soft_delete(self, return_id: UUID) -> CylinderReturn | None:
        return await self._repo.soft_delete(return_id)

    async def next_return_number(self) -> str:
        count = await self.session.scalar(
            select(func.count())
            .select_from(CylinderReturn)
            .where(CylinderReturn.deleted_at.is_(None))
        )
        return f"CR-{(int(count or 0) + 1):05d}"


async def load_cylinders(session: AsyncSession, cylinder_id: UUID) -> list[CylinderSize]:
    result = await session.execute(
        select(CylinderSize)
        .where(CylinderSize.cylinder_id == cylinder_id)
        .order_by(CylinderSize.position)
    )
    return list(result.scalars().all())


async def load_colors(session: AsyncSession, cylinder_id: UUID) -> list[CylinderColor]:
    result = await session.execute(
        select(CylinderColor)
        .where(CylinderColor.cylinder_id == cylinder_id)
        .order_by(CylinderColor.position)
    )
    return list(result.scalars().all())


async def load_pauses(session: AsyncSession, cylinder_id: UUID) -> list[CylinderPause]:
    result = await session.execute(
        select(CylinderPause)
        .where(CylinderPause.cylinder_id == cylinder_id)
        .order_by(CylinderPause.paused_at)
    )
    return list(result.scalars().all())


async def replace_cylinders(
    session: AsyncSession,
    cylinder_id: UUID,
    cylinders: list[dict[str, object]],
) -> None:
    existing = await session.execute(
        select(CylinderSize).where(CylinderSize.cylinder_id == cylinder_id)
    )
    for row in existing.scalars().all():
        await session.delete(row)
    await session.flush()
    for index, item in enumerate(cylinders, start=1):
        session.add(
            CylinderSize(
                cylinder_id=cylinder_id,
                position=index,
                width=item["width"],
                circumference=item["circumference"],
            )
        )


async def replace_colors(
    session: AsyncSession,
    cylinder_id: UUID,
    colors: list[dict[str, object]],
) -> None:
    existing = await session.execute(
        select(CylinderColor).where(CylinderColor.cylinder_id == cylinder_id)
    )
    for row in existing.scalars().all():
        await session.delete(row)
    await session.flush()
    for index, item in enumerate(colors, start=1):
        session.add(CylinderColor(cylinder_id=cylinder_id, position=index, name=item["name"]))
