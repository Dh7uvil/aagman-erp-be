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
from app.inventory.jobs.models import CylinderReturn, Job, JobColor, JobCylinder, JobPause


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Job,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "job_number", "product_name", "status"}
            ),
            allowed_filter_fields=frozenset({"status", "company_id"}),
            search_fields=frozenset({"job_number", "product_name"}),
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
    ) -> tuple[Sequence[Job], int]:
        return await self._repo.list(
            page=page,
            common_filter=common_filter,
            filters=filters,
            extra_criteria=extra_criteria,
        )

    async def get(self, job_id: UUID) -> Job | None:
        return await self._repo.get(job_id)

    async def create(self, values: dict[str, object]) -> Job:
        return await self._repo.create(values)

    async def update(self, job_id: UUID, values: dict[str, object]) -> Job | None:
        return await self._repo.update(job_id, values)

    async def soft_delete(self, job_id: UUID) -> Job | None:
        return await self._repo.soft_delete(job_id)

    async def next_job_number(self) -> str:
        count = await self.session.scalar(
            select(func.count()).select_from(Job).where(Job.deleted_at.is_(None))
        )
        return f"JOB-{(int(count or 0) + 1):05d}"


class CylinderReturnRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            CylinderReturn,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "return_number"}),
            allowed_filter_fields=frozenset({"company_id", "job_id"}),
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

    async def get_by_job(self, job_id: UUID) -> CylinderReturn | None:
        statement = select(CylinderReturn).where(
            CylinderReturn.job_id == job_id,
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
            select(func.count()).select_from(CylinderReturn).where(CylinderReturn.deleted_at.is_(None))
        )
        return f"CR-{(int(count or 0) + 1):05d}"


async def load_cylinders(session: AsyncSession, job_id: UUID) -> list[JobCylinder]:
    result = await session.execute(
        select(JobCylinder).where(JobCylinder.job_id == job_id).order_by(JobCylinder.position)
    )
    return list(result.scalars().all())


async def load_colors(session: AsyncSession, job_id: UUID) -> list[JobColor]:
    result = await session.execute(
        select(JobColor).where(JobColor.job_id == job_id).order_by(JobColor.position)
    )
    return list(result.scalars().all())


async def load_pauses(session: AsyncSession, job_id: UUID) -> list[JobPause]:
    result = await session.execute(
        select(JobPause).where(JobPause.job_id == job_id).order_by(JobPause.paused_at)
    )
    return list(result.scalars().all())


async def replace_cylinders(
    session: AsyncSession,
    job_id: UUID,
    cylinders: list[dict[str, object]],
) -> None:
    existing = await session.execute(select(JobCylinder).where(JobCylinder.job_id == job_id))
    for row in existing.scalars().all():
        await session.delete(row)
    for index, item in enumerate(cylinders, start=1):
        session.add(
            JobCylinder(
                job_id=job_id,
                position=index,
                width=item["width"],
                circumference=item["circumference"],
            )
        )


async def replace_colors(
    session: AsyncSession,
    job_id: UUID,
    colors: list[dict[str, object]],
) -> None:
    existing = await session.execute(select(JobColor).where(JobColor.job_id == job_id))
    for row in existing.scalars().all():
        await session.delete(row)
    for index, item in enumerate(colors, start=1):
        session.add(JobColor(job_id=job_id, position=index, name=item["name"]))
