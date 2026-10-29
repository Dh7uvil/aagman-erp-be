"""Dashboard aggregation queries."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.enums import JobStatus, MaterialCategoryKind, MaterialMovementDirection
from app.identity.models import Company
from app.inventory.jobs.models import CylinderReturn, Job, JobPause
from app.inventory.models import InventoryUnit, MaterialCategory, MaterialMovement


def _job_active() -> tuple[object, ...]:
    return (Job.deleted_at.is_(None),)


def _datetime_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _datetime_end(d: date) -> datetime:
    return datetime.combine(d, time.max, tzinfo=timezone.utc)


class DashboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def job_status_counts(self) -> list[tuple[str, int]]:
        rows = await self.session.execute(
            select(Job.status, func.count())
            .where(*_job_active())
            .group_by(Job.status)
        )
        return [(str(status), int(count)) for status, count in rows.all()]

    async def job_kpi_counts(
        self,
    ) -> tuple[int, int, int, int, Decimal | None]:
        active_statuses = (JobStatus.ACTIVE.value, JobStatus.RESUMED.value)
        active = await self.session.scalar(
            select(func.count())
            .select_from(Job)
            .where(*_job_active(), Job.status.in_(active_statuses))
        )
        paused = await self.session.scalar(
            select(func.count())
            .select_from(Job)
            .where(*_job_active(), Job.status == JobStatus.PAUSED.value)
        )
        cylinders = await self.session.scalar(
            select(func.coalesce(func.sum(Job.cylinder_count), 0))
            .select_from(Job)
            .where(*_job_active(), Job.status != JobStatus.RETURNED.value)
        )
        awaiting = await self.session.scalar(
            select(func.count())
            .select_from(Job)
            .outerjoin(
                CylinderReturn,
                (CylinderReturn.job_id == Job.id) & (CylinderReturn.deleted_at.is_(None)),
            )
            .where(
                *_job_active(),
                Job.status == JobStatus.COMPLETED.value,
                CylinderReturn.id.is_(None),
            )
        )
        cost_sum = await self.session.scalar(
            select(func.coalesce(func.sum(Job.cylinder_cost), 0))
            .select_from(Job)
            .where(*_job_active(), Job.status != JobStatus.RETURNED.value)
        )
        cost = Decimal(cost_sum) if cost_sum is not None else Decimal("0")
        return (
            int(active or 0),
            int(paused or 0),
            int(cylinders or 0),
            int(awaiting or 0),
            cost,
        )

    async def job_activity_buckets(
        self,
        *,
        date_from: date,
        date_to: date,
        weekly: bool,
    ) -> list[tuple[date, int, int]]:
        start_dt = _datetime_start(date_from)
        end_dt = _datetime_end(date_to)

        if weekly:
            job_bucket = cast(func.date_trunc("week", Job.created_at), Date)
            return_bucket = cast(func.date_trunc("week", CylinderReturn.created_at), Date)
        else:
            job_bucket = cast(Job.created_at, Date)
            return_bucket = cast(CylinderReturn.created_at, Date)

        job_rows = await self.session.execute(
            select(job_bucket, func.count())
            .where(
                *_job_active(),
                Job.created_at >= start_dt,
                Job.created_at <= end_dt,
            )
            .group_by(job_bucket)
            .order_by(job_bucket)
        )
        jobs_by_bucket = {row[0]: int(row[1]) for row in job_rows.all() if row[0] is not None}

        return_rows = await self.session.execute(
            select(return_bucket, func.count())
            .where(
                CylinderReturn.deleted_at.is_(None),
                CylinderReturn.created_at >= start_dt,
                CylinderReturn.created_at <= end_dt,
            )
            .group_by(return_bucket)
            .order_by(return_bucket)
        )
        returns_by_bucket = {
            row[0]: int(row[1]) for row in return_rows.all() if row[0] is not None
        }

        all_keys = sorted(set(jobs_by_bucket) | set(returns_by_bucket))
        return [
            (bucket, jobs_by_bucket.get(bucket, 0), returns_by_bucket.get(bucket, 0))
            for bucket in all_keys
        ]

    async def top_companies_by_active_jobs(self, *, limit: int = 5) -> list[tuple[UUID, str, int, int]]:
        active_statuses = (JobStatus.ACTIVE.value, JobStatus.RESUMED.value)
        rows = await self.session.execute(
            select(
                Job.company_id,
                Company.name,
                func.count(),
                func.coalesce(func.sum(Job.cylinder_count), 0),
            )
            .join(Company, Company.id == Job.company_id)
            .where(
                *_job_active(),
                Job.status.in_(active_statuses),
                Company.deleted_at.is_(None),
            )
            .group_by(Job.company_id, Company.name)
            .order_by(func.count().desc(), func.sum(Job.cylinder_count).desc())
            .limit(limit)
        )
        return [
            (company_id, name, int(job_count), int(cylinders or 0))
            for company_id, name, job_count, cylinders in rows.all()
        ]

    async def longest_open_pauses(self, *, limit: int = 5) -> list[tuple[Job, str, JobPause]]:
        rows = await self.session.execute(
            select(Job, Company.name, JobPause)
            .join(JobPause, JobPause.job_id == Job.id)
            .join(Company, Company.id == Job.company_id)
            .where(
                *_job_active(),
                JobPause.resumed_at.is_(None),
                Company.deleted_at.is_(None),
            )
            .order_by(JobPause.paused_at.asc())
            .limit(limit)
        )
        return [(job, company_name, pause) for job, company_name, pause in rows.all()]

    async def materials_sku_kpis(
        self,
    ) -> tuple[int, Decimal, int]:
        sku_criteria = (
            MaterialCategory.category_kind == MaterialCategoryKind.SKU.value,
            MaterialCategory.deleted_at.is_(None),
            MaterialCategory.is_active.is_(True),
        )
        active_count = await self.session.scalar(
            select(func.count()).select_from(MaterialCategory).where(*sku_criteria)
        )
        total_kg = await self.session.scalar(
            select(func.coalesce(func.sum(MaterialCategory.total_kg), 0)).where(*sku_criteria)
        )
        out_of_stock = await self.session.scalar(
            select(func.count())
            .select_from(MaterialCategory)
            .where(*sku_criteria, MaterialCategory.total_kg <= 0)
        )
        return (
            int(active_count or 0),
            Decimal(total_kg or 0),
            int(out_of_stock or 0),
        )

    async def materials_stock_value_kg_priced(self) -> tuple[Decimal, int]:
        micron = aliased(MaterialCategory)
        rows = await self.session.execute(
            select(
                func.coalesce(
                    func.sum(MaterialCategory.total_kg * micron.price_per_unit),
                    0,
                ),
                func.count(),
            )
            .select_from(MaterialCategory)
            .join(micron, MaterialCategory.parent_id == micron.id)
            .join(InventoryUnit, InventoryUnit.id == micron.price_unit_id)
            .where(
                MaterialCategory.category_kind == MaterialCategoryKind.SKU.value,
                MaterialCategory.deleted_at.is_(None),
                MaterialCategory.is_active.is_(True),
                micron.deleted_at.is_(None),
                InventoryUnit.deleted_at.is_(None),
                InventoryUnit.code == "kg",
                micron.price_per_unit.is_not(None),
            )
        )
        row = rows.one()
        return Decimal(row[0] or 0), int(row[1] or 0)

    async def movement_kg_buckets(
        self,
        *,
        date_from: date,
        date_to: date,
        weekly: bool,
    ) -> list[tuple[date, Decimal, Decimal]]:
        if weekly:
            bucket_expr = cast(func.date_trunc("week", MaterialMovement.movement_date), Date)
        else:
            bucket_expr = MaterialMovement.movement_date

        rows = await self.session.execute(
            select(
                bucket_expr,
                MaterialMovement.direction,
                func.coalesce(func.sum(MaterialMovement.kilograms), 0),
            )
            .where(
                MaterialMovement.deleted_at.is_(None),
                MaterialMovement.movement_date >= date_from,
                MaterialMovement.movement_date <= date_to,
                MaterialMovement.direction.in_(
                    (
                        MaterialMovementDirection.IN.value,
                        MaterialMovementDirection.OUT.value,
                    )
                ),
            )
            .group_by(bucket_expr, MaterialMovement.direction)
            .order_by(bucket_expr)
        )
        merged: dict[date, tuple[Decimal, Decimal]] = {}
        for bucket, direction, sum_kg in rows.all():
            if bucket is None:
                continue
            in_k, out_k = merged.get(bucket, (Decimal("0"), Decimal("0")))
            if direction == MaterialMovementDirection.IN.value:
                in_k += Decimal(sum_kg)
            else:
                out_k += Decimal(sum_kg)
            merged[bucket] = (in_k, out_k)
        return [(bucket, in_k, out_k) for bucket, (in_k, out_k) in sorted(merged.items())]

    async def stock_kg_by_product(self) -> list[tuple[str, Decimal]]:
        micron = aliased(MaterialCategory)
        product = aliased(MaterialCategory)
        rows = await self.session.execute(
            select(product.name, func.coalesce(func.sum(MaterialCategory.total_kg), 0))
            .select_from(MaterialCategory)
            .join(micron, MaterialCategory.parent_id == micron.id)
            .join(product, micron.parent_id == product.id)
            .where(
                MaterialCategory.category_kind == MaterialCategoryKind.SKU.value,
                MaterialCategory.deleted_at.is_(None),
                MaterialCategory.is_active.is_(True),
                micron.deleted_at.is_(None),
                product.deleted_at.is_(None),
            )
            .group_by(product.name)
            .order_by(func.sum(MaterialCategory.total_kg).desc())
        )
        return [(name, Decimal(kg or 0)) for name, kg in rows.all()]

    async def sku_out_kg_in_range(
        self,
        *,
        date_from: date,
        date_to: date,
    ) -> dict[UUID, Decimal]:
        rows = await self.session.execute(
            select(
                MaterialMovement.category_id,
                func.coalesce(func.sum(MaterialMovement.kilograms), 0),
            )
            .where(
                MaterialMovement.deleted_at.is_(None),
                MaterialMovement.movement_date >= date_from,
                MaterialMovement.movement_date <= date_to,
                MaterialMovement.direction == MaterialMovementDirection.OUT.value,
            )
            .group_by(MaterialMovement.category_id)
        )
        return {category_id: Decimal(kg or 0) for category_id, kg in rows.all()}

    async def list_active_skus(self) -> list[MaterialCategory]:
        result = await self.session.execute(
            select(MaterialCategory)
            .where(
                MaterialCategory.category_kind == MaterialCategoryKind.SKU.value,
                MaterialCategory.deleted_at.is_(None),
                MaterialCategory.is_active.is_(True),
            )
            .order_by(MaterialCategory.name)
        )
        return list(result.scalars().all())
