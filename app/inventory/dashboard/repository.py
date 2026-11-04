"""Dashboard aggregation queries."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.enums import CylinderStatus, MaterialCategoryKind, MaterialMovementDirection
from app.identity.models import Company
from app.inventory.cylinders.models import CylinderReturn, Cylinder, CylinderPause
from app.inventory.adhesives.models import (
    AdhesiveBrand,
    AdhesiveCode,
    AdhesiveLine,
    AdhesiveMovement,
    AdhesiveSheet,
)
from app.inventory.inks.models import InkBrand, InkColor, InkLine, InkMovement, InkSheet
from app.inventory.models import InventoryUnit, MaterialCategory, MaterialMovement


def _job_active() -> tuple[object, ...]:
    return (Cylinder.deleted_at.is_(None),)


def _datetime_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _datetime_end(d: date) -> datetime:
    return datetime.combine(d, time.max, tzinfo=timezone.utc)


class DashboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def job_status_counts(self) -> list[tuple[str, int]]:
        rows = await self.session.execute(
            select(Cylinder.status, func.count())
            .where(*_job_active())
            .group_by(Cylinder.status)
        )
        return [(str(status), int(count)) for status, count in rows.all()]

    async def job_kpi_counts(
        self,
    ) -> tuple[int, int, int, int, Decimal | None]:
        active_statuses = (CylinderStatus.ACTIVE.value,)
        active = await self.session.scalar(
            select(func.count())
            .select_from(Cylinder)
            .where(*_job_active(), Cylinder.status.in_(active_statuses))
        )
        paused = await self.session.scalar(
            select(func.count())
            .select_from(Cylinder)
            .where(*_job_active(), Cylinder.status == CylinderStatus.PAUSED.value)
        )
        cylinders = await self.session.scalar(
            select(func.coalesce(func.sum(Cylinder.cylinder_count), 0))
            .select_from(Cylinder)
            .where(*_job_active(), Cylinder.status == CylinderStatus.RETURNED.value)
        )
        awaiting = await self.session.scalar(
            select(func.count())
            .select_from(Cylinder)
            .outerjoin(
                CylinderReturn,
                (CylinderReturn.cylinder_id == Cylinder.id) & (CylinderReturn.deleted_at.is_(None)),
            )
            .where(
                *_job_active(),
                Cylinder.status == CylinderStatus.COMPLETED.value,
                CylinderReturn.id.is_(None),
            )
        )
        cost_sum = await self.session.scalar(
            select(
                func.coalesce(
                    func.sum(Cylinder.cylinder_cost * Cylinder.cylinder_count),
                    0,
                )
            )
            .select_from(Cylinder)
            .where(*_job_active(), Cylinder.status == CylinderStatus.ACTIVE.value)
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
            job_bucket = cast(func.date_trunc("week", Cylinder.created_at), Date)
            return_bucket = cast(func.date_trunc("week", CylinderReturn.created_at), Date)
        else:
            job_bucket = cast(Cylinder.created_at, Date)
            return_bucket = cast(CylinderReturn.created_at, Date)

        job_rows = await self.session.execute(
            select(job_bucket, func.count())
            .where(
                *_job_active(),
                Cylinder.created_at >= start_dt,
                Cylinder.created_at <= end_dt,
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

    async def top_companies_by_active_cylinders(self, *, limit: int = 5) -> list[tuple[UUID, str, int, int]]:
        active_statuses = (CylinderStatus.ACTIVE.value,)
        rows = await self.session.execute(
            select(
                Cylinder.company_id,
                Company.name,
                func.count(),
                func.coalesce(func.sum(Cylinder.cylinder_count), 0),
            )
            .join(Company, Company.id == Cylinder.company_id)
            .where(
                *_job_active(),
                Cylinder.status.in_(active_statuses),
                Company.deleted_at.is_(None),
            )
            .group_by(Cylinder.company_id, Company.name)
            .order_by(func.count().desc(), func.sum(Cylinder.cylinder_count).desc())
            .limit(limit)
        )
        return [
            (company_id, name, int(job_count), int(cylinders or 0))
            for company_id, name, job_count, cylinders in rows.all()
        ]

    async def longest_open_pauses(self, *, limit: int = 5) -> list[tuple[Cylinder, str, CylinderPause]]:
        rows = await self.session.execute(
            select(Cylinder, Company.name, CylinderPause)
            .join(CylinderPause, CylinderPause.cylinder_id == Cylinder.id)
            .join(Company, Company.id == Cylinder.company_id)
            .where(
                *_job_active(),
                CylinderPause.resumed_at.is_(None),
                Company.deleted_at.is_(None),
            )
            .order_by(CylinderPause.paused_at.asc())
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

    async def list_kg_priced_sku_valuation_rows(
        self,
    ) -> list[tuple[UUID, Decimal, Decimal | None]]:
        """Active SKUs with kg-priced microns: (sku_id, total_kg, micron current price)."""
        micron = aliased(MaterialCategory)
        rows = await self.session.execute(
            select(
                MaterialCategory.id,
                MaterialCategory.total_kg,
                micron.price_per_unit,
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
        result: list[tuple[UUID, Decimal, Decimal | None]] = []
        for sku_id, total_kg, micron_price in rows.all():
            result.append(
                (
                    sku_id,
                    Decimal(total_kg or 0),
                    Decimal(micron_price) if micron_price is not None else None,
                )
            )
        return result

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

    async def list_dead_stock_skus(
        self,
        *,
        as_of: date | None = None,
        idle_days: int = 60,
    ) -> list[tuple[UUID, str, Decimal, date]]:
        """Active SKUs with kg on hand and no stock activity within idle_days."""
        today = as_of or date.today()
        cutoff = today - timedelta(days=idle_days)
        movement_directions = (
            MaterialMovementDirection.IN.value,
            MaterialMovementDirection.OUT.value,
            MaterialMovementDirection.OPENING.value,
        )
        created_date = cast(MaterialCategory.created_at, Date)
        last_activity = func.coalesce(func.max(MaterialMovement.movement_date), created_date)

        rows = await self.session.execute(
            select(
                MaterialCategory.id,
                MaterialCategory.name,
                MaterialCategory.total_kg,
                last_activity.label("last_activity"),
            )
            .outerjoin(
                MaterialMovement,
                and_(
                    MaterialMovement.category_id == MaterialCategory.id,
                    MaterialMovement.deleted_at.is_(None),
                    MaterialMovement.direction.in_(movement_directions),
                ),
            )
            .where(
                MaterialCategory.category_kind == MaterialCategoryKind.SKU.value,
                MaterialCategory.deleted_at.is_(None),
                MaterialCategory.is_active.is_(True),
                MaterialCategory.total_kg > 0,
            )
            .group_by(
                MaterialCategory.id,
                MaterialCategory.name,
                MaterialCategory.total_kg,
                MaterialCategory.created_at,
            )
            .having(last_activity < cutoff)
            .order_by(last_activity.asc())
        )
        return [
            (
                sku_id,
                name,
                Decimal(total_kg or 0),
                last_activity_date,
            )
            for sku_id, name, total_kg, last_activity_date in rows.all()
        ]

    async def ink_movement_buckets(
        self,
        *,
        date_from: date,
        date_to: date,
        weekly: bool,
    ) -> list[tuple[date, Decimal, Decimal]]:
        if weekly:
            bucket_expr = cast(func.date_trunc("week", InkMovement.movement_date), Date)
        else:
            bucket_expr = InkMovement.movement_date

        rows = await self.session.execute(
            select(
                bucket_expr,
                InkMovement.direction,
                func.coalesce(func.sum(InkMovement.quantity), 0),
            )
            .where(
                InkMovement.deleted_at.is_(None),
                InkMovement.movement_date >= date_from,
                InkMovement.movement_date <= date_to,
                InkMovement.direction.in_(
                    (
                        MaterialMovementDirection.IN.value,
                        MaterialMovementDirection.OUT.value,
                    )
                ),
            )
            .group_by(bucket_expr, InkMovement.direction)
            .order_by(bucket_expr)
        )
        merged: dict[date, tuple[Decimal, Decimal]] = {}
        for bucket, direction, sum_qty in rows.all():
            if bucket is None:
                continue
            in_q, out_q = merged.get(bucket, (Decimal("0"), Decimal("0")))
            if direction == MaterialMovementDirection.IN.value:
                in_q += Decimal(sum_qty)
            else:
                out_q += Decimal(sum_qty)
            merged[bucket] = (in_q, out_q)
        return [(bucket, in_q, out_q) for bucket, (in_q, out_q) in sorted(merged.items())]

    async def stock_qty_by_company(self) -> list[tuple[str, Decimal]]:
        rows = await self.session.execute(
            select(Company.name, func.coalesce(func.sum(InkLine.total_qty), 0))
            .select_from(InkLine)
            .join(InkSheet, InkLine.ink_sheet_id == InkSheet.id)
            .join(Company, InkSheet.company_id == Company.id)
            .where(
                InkLine.deleted_at.is_(None),
                InkSheet.deleted_at.is_(None),
                Company.deleted_at.is_(None),
            )
            .group_by(Company.name)
            .order_by(func.sum(InkLine.total_qty).desc())
        )
        return [(name, Decimal(qty or 0)) for name, qty in rows.all()]

    async def ink_line_out_qty_in_range(
        self,
        *,
        date_from: date,
        date_to: date,
    ) -> dict[UUID, Decimal]:
        rows = await self.session.execute(
            select(
                InkMovement.ink_line_id,
                func.coalesce(func.sum(InkMovement.quantity), 0),
            )
            .where(
                InkMovement.deleted_at.is_(None),
                InkMovement.movement_date >= date_from,
                InkMovement.movement_date <= date_to,
                InkMovement.direction == MaterialMovementDirection.OUT.value,
            )
            .group_by(InkMovement.ink_line_id)
        )
        return {line_id: Decimal(qty or 0) for line_id, qty in rows.all()}

    async def list_active_ink_lines(self) -> list[InkLine]:
        result = await self.session.execute(
            select(InkLine)
            .join(InkSheet, InkLine.ink_sheet_id == InkSheet.id)
            .where(
                InkLine.deleted_at.is_(None),
                InkSheet.deleted_at.is_(None),
            )
            .order_by(InkLine.created_at)
        )
        return list(result.scalars().all())

    async def list_dead_stock_ink_lines(
        self,
        *,
        as_of: date | None = None,
        idle_days: int = 30,
    ) -> list[tuple[UUID, str, Decimal, date]]:
        today = as_of or date.today()
        cutoff = today - timedelta(days=idle_days)
        movement_directions = (
            MaterialMovementDirection.IN.value,
            MaterialMovementDirection.OUT.value,
            MaterialMovementDirection.OPENING.value,
        )
        brand = aliased(InkBrand)
        color = aliased(InkColor)
        created_date = cast(InkLine.created_at, Date)
        last_activity = func.coalesce(func.max(InkMovement.movement_date), created_date)

        rows = await self.session.execute(
            select(
                InkLine.id,
                func.concat(brand.name, " · ", color.name).label("label"),
                InkLine.total_qty,
                last_activity.label("last_activity"),
            )
            .join(InkSheet, InkLine.ink_sheet_id == InkSheet.id)
            .join(brand, InkLine.brand_id == brand.id)
            .join(color, InkLine.color_id == color.id)
            .outerjoin(
                InkMovement,
                and_(
                    InkMovement.ink_line_id == InkLine.id,
                    InkMovement.deleted_at.is_(None),
                    InkMovement.direction.in_(movement_directions),
                ),
            )
            .where(
                InkLine.deleted_at.is_(None),
                InkSheet.deleted_at.is_(None),
                InkLine.total_qty > 0,
            )
            .group_by(
                InkLine.id,
                brand.name,
                color.name,
                InkLine.total_qty,
                InkLine.created_at,
            )
            .having(last_activity < cutoff)
            .order_by(last_activity.asc())
        )
        return [
            (line_id, name, Decimal(total_qty or 0), last_activity_date)
            for line_id, name, total_qty, last_activity_date in rows.all()
        ]

    async def adhesive_movement_buckets(
        self,
        *,
        date_from: date,
        date_to: date,
        weekly: bool,
    ) -> list[tuple[date, Decimal, Decimal]]:
        if weekly:
            bucket_expr = cast(func.date_trunc("week", AdhesiveMovement.movement_date), Date)
        else:
            bucket_expr = AdhesiveMovement.movement_date

        rows = await self.session.execute(
            select(
                bucket_expr,
                AdhesiveMovement.direction,
                func.coalesce(func.sum(AdhesiveMovement.quantity), 0),
            )
            .where(
                AdhesiveMovement.deleted_at.is_(None),
                AdhesiveMovement.movement_date >= date_from,
                AdhesiveMovement.movement_date <= date_to,
                AdhesiveMovement.direction.in_(
                    (
                        MaterialMovementDirection.IN.value,
                        MaterialMovementDirection.OUT.value,
                    )
                ),
            )
            .group_by(bucket_expr, AdhesiveMovement.direction)
            .order_by(bucket_expr)
        )
        merged: dict[date, tuple[Decimal, Decimal]] = {}
        for bucket, direction, sum_qty in rows.all():
            if bucket is None:
                continue
            in_q, out_q = merged.get(bucket, (Decimal("0"), Decimal("0")))
            if direction == MaterialMovementDirection.IN.value:
                in_q += Decimal(sum_qty)
            else:
                out_q += Decimal(sum_qty)
            merged[bucket] = (in_q, out_q)
        return [(bucket, in_q, out_q) for bucket, (in_q, out_q) in sorted(merged.items())]

    async def adhesive_stock_qty_by_company(self) -> list[tuple[str, Decimal]]:
        rows = await self.session.execute(
            select(Company.name, func.coalesce(func.sum(AdhesiveLine.total_qty), 0))
            .select_from(AdhesiveLine)
            .join(AdhesiveSheet, AdhesiveLine.adhesive_sheet_id == AdhesiveSheet.id)
            .join(Company, AdhesiveSheet.company_id == Company.id)
            .where(
                AdhesiveLine.deleted_at.is_(None),
                AdhesiveSheet.deleted_at.is_(None),
                Company.deleted_at.is_(None),
            )
            .group_by(Company.name)
            .order_by(func.sum(AdhesiveLine.total_qty).desc())
        )
        return [(name, Decimal(qty or 0)) for name, qty in rows.all()]

    async def adhesive_line_out_qty_in_range(
        self,
        *,
        date_from: date,
        date_to: date,
    ) -> dict[UUID, Decimal]:
        rows = await self.session.execute(
            select(
                AdhesiveMovement.adhesive_line_id,
                func.coalesce(func.sum(AdhesiveMovement.quantity), 0),
            )
            .where(
                AdhesiveMovement.deleted_at.is_(None),
                AdhesiveMovement.movement_date >= date_from,
                AdhesiveMovement.movement_date <= date_to,
                AdhesiveMovement.direction == MaterialMovementDirection.OUT.value,
            )
            .group_by(AdhesiveMovement.adhesive_line_id)
        )
        return {line_id: Decimal(qty or 0) for line_id, qty in rows.all()}

    async def list_active_adhesive_lines(self) -> list[AdhesiveLine]:
        result = await self.session.execute(
            select(AdhesiveLine)
            .join(AdhesiveSheet, AdhesiveLine.adhesive_sheet_id == AdhesiveSheet.id)
            .where(
                AdhesiveLine.deleted_at.is_(None),
                AdhesiveSheet.deleted_at.is_(None),
            )
            .order_by(AdhesiveLine.created_at)
        )
        return list(result.scalars().all())

    async def solvent_movement_buckets(
        self,
        *,
        date_from: date,
        date_to: date,
        weekly: bool,
    ) -> list[tuple[date, Decimal, Decimal]]:
        from app.inventory.solvents.models import SolventMovement

        if weekly:
            bucket_expr = cast(func.date_trunc("week", SolventMovement.movement_date), Date)
        else:
            bucket_expr = SolventMovement.movement_date

        rows = await self.session.execute(
            select(
                bucket_expr,
                SolventMovement.direction,
                func.coalesce(func.sum(SolventMovement.quantity), 0),
            )
            .where(
                SolventMovement.deleted_at.is_(None),
                SolventMovement.movement_date >= date_from,
                SolventMovement.movement_date <= date_to,
                SolventMovement.direction.in_(
                    (
                        MaterialMovementDirection.IN.value,
                        MaterialMovementDirection.OUT.value,
                    )
                ),
            )
            .group_by(bucket_expr, SolventMovement.direction)
            .order_by(bucket_expr)
        )
        merged: dict[date, tuple[Decimal, Decimal]] = {}
        for bucket, direction, sum_qty in rows.all():
            if bucket is None:
                continue
            in_q, out_q = merged.get(bucket, (Decimal("0"), Decimal("0")))
            if direction == MaterialMovementDirection.IN.value:
                in_q += Decimal(sum_qty)
            else:
                out_q += Decimal(sum_qty)
            merged[bucket] = (in_q, out_q)
        return [(bucket, in_q, out_q) for bucket, (in_q, out_q) in sorted(merged.items())]

    async def solvent_stock_qty_by_company(self) -> list[tuple[str, Decimal]]:
        from app.inventory.solvents.models import SolventLine, SolventSheet

        rows = await self.session.execute(
            select(Company.name, func.coalesce(func.sum(SolventLine.total_qty), 0))
            .select_from(SolventLine)
            .join(SolventSheet, SolventLine.solvent_sheet_id == SolventSheet.id)
            .join(Company, SolventSheet.company_id == Company.id)
            .where(
                SolventLine.deleted_at.is_(None),
                SolventSheet.deleted_at.is_(None),
                Company.deleted_at.is_(None),
            )
            .group_by(Company.name)
            .order_by(func.sum(SolventLine.total_qty).desc())
        )
        return [(name, Decimal(qty or 0)) for name, qty in rows.all()]

    async def solvent_line_out_qty_in_range(
        self,
        *,
        date_from: date,
        date_to: date,
    ) -> dict[UUID, Decimal]:
        from app.inventory.solvents.models import SolventMovement

        rows = await self.session.execute(
            select(
                SolventMovement.solvent_line_id,
                func.coalesce(func.sum(SolventMovement.quantity), 0),
            )
            .where(
                SolventMovement.deleted_at.is_(None),
                SolventMovement.movement_date >= date_from,
                SolventMovement.movement_date <= date_to,
                SolventMovement.direction == MaterialMovementDirection.OUT.value,
            )
            .group_by(SolventMovement.solvent_line_id)
        )
        return {line_id: Decimal(qty or 0) for line_id, qty in rows.all()}

    async def list_active_solvent_lines(self) -> list:
        from app.inventory.solvents.models import SolventLine, SolventSheet

        result = await self.session.execute(
            select(SolventLine)
            .join(SolventSheet, SolventLine.solvent_sheet_id == SolventSheet.id)
            .where(
                SolventLine.deleted_at.is_(None),
                SolventSheet.deleted_at.is_(None),
            )
            .order_by(SolventLine.created_at)
        )
        return list(result.scalars().all())
