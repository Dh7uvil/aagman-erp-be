"""Dashboard business logic."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import has_permission
from app.inventory.catalog import JOB_VIEW_PRICE, MATERIAL_VIEW_PRICE
from app.inventory.dashboard.repository import DashboardRepository
from app.inventory.dashboard.schemas import (
    DashboardRange,
    JobActivityBucket,
    JobStatusCount,
    JobsDashboard,
    JobsDashboardKpis,
    MaterialsDashboard,
    MaterialsDashboardKpis,
    MovementActivityBucket,
    OpenJobPause,
    ReorderWatchItem,
    StockByProduct,
    TopCompanyJobs,
    TopConsumedSku,
)


class DashboardService:
    _DISPLAY_QUANTUM = Decimal("0.01")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DashboardRepository(session)

    @classmethod
    def _quantize(cls, value: Decimal) -> Decimal:
        return value.quantize(cls._DISPLAY_QUANTUM)

    @staticmethod
    def _resolve_range(range_params: DashboardRange) -> tuple[date, date, bool]:
        end = range_params.date_to or date.today()
        start = range_params.date_from or (end - timedelta(days=29))
        if start > end:
            start, end = end, start
        span = (end - start).days + 1
        return start, end, span > 31

    async def jobs_overview(
        self,
        *,
        range_params: DashboardRange,
        permissions: frozenset[str],
    ) -> JobsDashboard:
        date_from, date_to, weekly = self._resolve_range(range_params)
        active, paused, cylinders, awaiting, cost_total = await self.repo.job_kpi_counts()
        can_view_price = has_permission(permissions, JOB_VIEW_PRICE)

        status_rows = await self.repo.job_status_counts()
        buckets = await self.repo.job_activity_buckets(
            date_from=date_from,
            date_to=date_to,
            weekly=weekly,
        )
        companies = await self.repo.top_companies_by_active_jobs(limit=5)
        pauses = await self.repo.longest_open_pauses(limit=5)

        now = datetime.now(timezone.utc)
        open_pauses: list[OpenJobPause] = []
        for job, company_name, pause in pauses:
            paused_at = pause.paused_at
            if paused_at.tzinfo is None:
                paused_at = paused_at.replace(tzinfo=timezone.utc)
            delta = now - paused_at
            days_paused = max(delta.days, 0)
            open_pauses.append(
                OpenJobPause(
                    job_id=str(job.id),
                    job_number=job.job_number,
                    company_name=company_name,
                    paused_at=pause.paused_at,
                    days_paused=days_paused,
                )
            )

        return JobsDashboard(
            date_from=date_from,
            date_to=date_to,
            kpis=JobsDashboardKpis(
                active_jobs=active,
                paused_jobs=paused,
                cylinders_in_circulation=cylinders,
                awaiting_return=awaiting,
                cylinder_cost_exposure=self._quantize(cost_total) if can_view_price else None,
            ),
            status_breakdown=[
                JobStatusCount(status=status, count=count) for status, count in status_rows
            ],
            activity_buckets=[
                JobActivityBucket(
                    bucket_start=bucket,
                    jobs_created=jobs_created,
                    returns_created=returns_created,
                )
                for bucket, jobs_created, returns_created in buckets
            ],
            top_companies=[
                TopCompanyJobs(
                    company_id=str(company_id),
                    company_name=name,
                    active_jobs=job_count,
                    cylinder_count=cylinder_count,
                )
                for company_id, name, job_count, cylinder_count in companies
            ],
            open_pauses=open_pauses,
        )

    async def materials_overview(
        self,
        *,
        range_params: DashboardRange,
        permissions: frozenset[str],
    ) -> MaterialsDashboard:
        date_from, date_to, weekly = self._resolve_range(range_params)
        days_in_range = (date_to - date_from).days + 1
        can_view_price = has_permission(permissions, MATERIAL_VIEW_PRICE)

        active_skus, total_kg, out_of_stock = await self.repo.materials_sku_kpis()
        stock_value: Decimal | None = None
        valued_count = 0
        if can_view_price:
            stock_value_raw, valued_count = await self.repo.materials_stock_value_kg_priced()
            stock_value = self._quantize(stock_value_raw)

        movement_rows = await self.repo.movement_kg_buckets(
            date_from=date_from,
            date_to=date_to,
            weekly=weekly,
        )
        stock_by_product = await self.repo.stock_kg_by_product()
        out_by_sku = await self.repo.sku_out_kg_in_range(date_from=date_from, date_to=date_to)
        skus = await self.repo.list_active_skus()

        reorder: list[ReorderWatchItem] = []
        for sku in skus:
            total = Decimal(sku.total_kg or 0)
            if total <= 0:
                continue
            out_kg = out_by_sku.get(sku.id, Decimal("0"))
            if out_kg <= 0:
                continue
            avg_daily = out_kg / Decimal(days_in_range)
            if avg_daily <= 0:
                continue
            days_of_cover = total / avg_daily
            reorder.append(
                ReorderWatchItem(
                    material_id=str(sku.id),
                    name=sku.name,
                    total_kg=self._quantize(total),
                    avg_daily_out_kg=self._quantize(avg_daily),
                    days_of_cover=self._quantize(days_of_cover),
                )
            )
        reorder.sort(key=lambda item: item.days_of_cover)
        reorder = reorder[:5]

        top_consumed: list[TopConsumedSku] = []
        sku_names = {sku.id: sku.name for sku in skus}
        for material_id, out_kg in sorted(
            out_by_sku.items(),
            key=lambda pair: pair[1],
            reverse=True,
        )[:5]:
            name = sku_names.get(material_id)
            if name is None:
                continue
            top_consumed.append(
                TopConsumedSku(
                    material_id=str(material_id),
                    name=name,
                    out_kg=self._quantize(out_kg),
                )
            )

        return MaterialsDashboard(
            date_from=date_from,
            date_to=date_to,
            kpis=MaterialsDashboardKpis(
                active_skus=active_skus,
                total_kg_on_hand=self._quantize(total_kg),
                out_of_stock_skus=out_of_stock,
                stock_value=stock_value,
                valued_sku_count=valued_count if can_view_price else 0,
            ),
            movement_buckets=[
                MovementActivityBucket(
                    bucket_start=bucket,
                    in_kg=self._quantize(in_kg),
                    out_kg=self._quantize(out_kg),
                )
                for bucket, in_kg, out_kg in movement_rows
            ],
            stock_by_product=[
                StockByProduct(product_name=name, total_kg=self._quantize(kg))
                for name, kg in stock_by_product
            ],
            reorder_watchlist=reorder,
            top_consumed=top_consumed,
        )
