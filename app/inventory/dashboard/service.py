"""Dashboard business logic."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory.adhesives.models import AdhesiveBrand, AdhesiveCode
from app.inventory.inks.models import InkBrand, InkColor

from app.core.permissions import has_permission
from app.inventory.catalog import (
    ADHESIVE_VIEW_PRICE,
    CYLINDER_VIEW_PRICE,
    INK_VIEW_PRICE,
    MATERIAL_VIEW_PRICE,
)
from app.inventory.dashboard.repository import DashboardRepository
from app.inventory.pricing import valuation_unit_price
from app.inventory.repository import MovementRepository
from app.inventory.dashboard.schemas import (
    DashboardRange,
    CylinderActivityBucket,
    CylinderStatusCount,
    CylindersDashboard,
    CylindersDashboardKpis,
    DeadStockItem,
    MaterialsDashboard,
    MaterialsDashboardKpis,
    MovementActivityBucket,
    OpenCylinderPause,
    ReorderWatchItem,
    StockByProduct,
    TopCompanyCylinders,
    TopConsumedSku,
    AdhesivesDashboard,
    AdhesivesDashboardKpis,
    InkDeadStockItem,
    InksDashboard,
    InksDashboardKpis,
    StockByCompany,
    TopConsumedAdhesiveLine,
    TopConsumedInkLine,
)


class DashboardService:
    _DISPLAY_QUANTUM = Decimal("0.01")
    _DEAD_STOCK_IDLE_DAYS = 60
    _INK_DEAD_STOCK_IDLE_DAYS = 30

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DashboardRepository(session)

    @classmethod
    def _quantize(cls, value: Decimal) -> Decimal:
        return value.quantize(cls._DISPLAY_QUANTUM)

    async def _materials_stock_value_kg_priced(self) -> tuple[Decimal, int]:
        rows = await self.repo.list_kg_priced_sku_valuation_rows()
        if not rows:
            return Decimal("0"), 0
        sku_ids = [sku_id for sku_id, _, _ in rows]
        stats_map = await MovementRepository(self.session).purchase_price_stats_by_category_ids(
            sku_ids,
        )
        total = Decimal("0")
        valued_count = 0
        for sku_id, total_kg, micron_price in rows:
            unit_price = valuation_unit_price(micron_price, stats_map.get(sku_id))
            if unit_price is None:
                continue
            total += total_kg * unit_price
            valued_count += 1
        return total, valued_count

    @staticmethod
    def _resolve_range(range_params: DashboardRange) -> tuple[date, date, bool]:
        end = range_params.date_to or date.today()
        start = range_params.date_from or (end - timedelta(days=29))
        if start > end:
            start, end = end, start
        span = (end - start).days + 1
        return start, end, span > 31

    async def cylinders_overview(
        self,
        *,
        range_params: DashboardRange,
        permissions: frozenset[str],
    ) -> CylindersDashboard:
        date_from, date_to, weekly = self._resolve_range(range_params)
        active, paused, cylinders, awaiting, cost_total = await self.repo.job_kpi_counts()
        can_view_price = has_permission(permissions, CYLINDER_VIEW_PRICE)

        status_rows = await self.repo.job_status_counts()
        buckets = await self.repo.job_activity_buckets(
            date_from=date_from,
            date_to=date_to,
            weekly=weekly,
        )
        companies = await self.repo.top_companies_by_active_cylinders(limit=5)
        pauses = await self.repo.longest_open_pauses(limit=5)

        now = datetime.now(timezone.utc)
        open_pauses: list[OpenCylinderPause] = []
        for job, company_name, pause in pauses:
            paused_at = pause.paused_at
            if paused_at.tzinfo is None:
                paused_at = paused_at.replace(tzinfo=timezone.utc)
            delta = now - paused_at
            days_paused = max(delta.days, 0)
            open_pauses.append(
                OpenCylinderPause(
                    cylinder_id=str(job.id),
                    cylinder_number=job.cylinder_number,
                    company_name=company_name,
                    paused_at=pause.paused_at,
                    days_paused=days_paused,
                )
            )

        return CylindersDashboard(
            date_from=date_from,
            date_to=date_to,
            kpis=CylindersDashboardKpis(
                active_cylinders=active,
                paused_cylinders=paused,
                cylinders_in_circulation=cylinders,
                awaiting_return=awaiting,
                cylinder_cost_exposure=self._quantize(cost_total) if can_view_price else None,
            ),
            status_breakdown=[
                CylinderStatusCount(status=status, count=count) for status, count in status_rows
            ],
            activity_buckets=[
                CylinderActivityBucket(
                    bucket_start=bucket,
                    cylinders_created=cylinders_created,
                    returns_created=returns_created,
                )
                for bucket, cylinders_created, returns_created in buckets
            ],
            top_companies=[
                TopCompanyCylinders(
                    company_id=str(company_id),
                    company_name=name,
                    active_cylinders=job_count,
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
            stock_value_raw, valued_count = await self._materials_stock_value_kg_priced()
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

        today = date.today()
        dead_stock_rows = await self.repo.list_dead_stock_skus(
            as_of=today,
            idle_days=self._DEAD_STOCK_IDLE_DAYS,
        )
        dead_stock: list[DeadStockItem] = []
        for material_id, name, total, last_activity in dead_stock_rows:
            days_idle = (today - last_activity).days
            dead_stock.append(
                DeadStockItem(
                    material_id=str(material_id),
                    name=name,
                    total_kg=self._quantize(total),
                    days_idle=days_idle,
                    last_activity_date=last_activity,
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
                dead_stock_skus=len(dead_stock),
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
            dead_stock=dead_stock,
        )

    async def inks_overview(
        self,
        *,
        range_params: DashboardRange,
        permissions: frozenset[str],
    ) -> InksDashboard:
        date_from, date_to, weekly = self._resolve_range(range_params)
        can_view_price = has_permission(permissions, INK_VIEW_PRICE)

        lines = await self.repo.list_active_ink_lines()
        active_lines = len(lines)
        total_qty = sum((Decimal(line.total_qty or 0) for line in lines), Decimal("0"))
        out_of_stock = sum(
            1 for line in lines if (line.total_qty or Decimal("0")) <= 0
        )

        stock_value = Decimal("0")
        valued_count = 0
        if can_view_price:
            for line in lines:
                qty = Decimal(line.total_qty or 0)
                rate = line.ink_rate
                if qty > 0 and rate is not None:
                    stock_value += qty * Decimal(rate)
                    valued_count += 1

        movement_rows = await self.repo.ink_movement_buckets(
            date_from=date_from,
            date_to=date_to,
            weekly=weekly,
        )
        stock_by_company = await self.repo.stock_qty_by_company()
        out_by_line = await self.repo.ink_line_out_qty_in_range(
            date_from=date_from,
            date_to=date_to,
        )

        line_labels: dict[UUID, str] = {}
        brand_ids = {line.brand_id for line in lines}
        color_ids = {line.color_id for line in lines}
        if brand_ids:
            brand_rows = await self.session.execute(
                select(InkBrand).where(InkBrand.id.in_(brand_ids))
            )
            brands = {row.id: row.name for row in brand_rows.scalars()}
        else:
            brands = {}
        if color_ids:
            color_rows = await self.session.execute(
                select(InkColor).where(InkColor.id.in_(color_ids))
            )
            colors = {row.id: row.name for row in color_rows.scalars()}
        else:
            colors = {}
        for line in lines:
            line_labels[line.id] = f"{brands.get(line.brand_id, '')} · {colors.get(line.color_id, '')}"

        top_consumed: list[TopConsumedInkLine] = []
        for line_id, out_qty in sorted(out_by_line.items(), key=lambda pair: pair[1], reverse=True)[:5]:
            name = line_labels.get(line_id)
            if name is None:
                continue
            top_consumed.append(
                TopConsumedInkLine(
                    ink_line_id=str(line_id),
                    name=name,
                    out_qty=self._quantize(out_qty),
                )
            )

        today = date.today()
        dead_stock_rows = await self.repo.list_dead_stock_ink_lines(
            as_of=today,
            idle_days=self._INK_DEAD_STOCK_IDLE_DAYS,
        )
        dead_stock: list[InkDeadStockItem] = []
        for line_id, name, total, last_activity in dead_stock_rows:
            days_idle = (today - last_activity).days
            dead_stock.append(
                InkDeadStockItem(
                    ink_line_id=str(line_id),
                    name=name,
                    total_qty=self._quantize(total),
                    days_idle=days_idle,
                    last_activity_date=last_activity,
                )
            )

        return InksDashboard(
            date_from=date_from,
            date_to=date_to,
            kpis=InksDashboardKpis(
                active_lines=active_lines,
                total_qty_on_hand=self._quantize(total_qty),
                out_of_stock_lines=out_of_stock,
                stock_value=self._quantize(stock_value) if can_view_price else None,
                valued_line_count=valued_count if can_view_price else 0,
                dead_stock_lines=len(dead_stock),
            ),
            movement_buckets=[
                MovementActivityBucket(
                    bucket_start=bucket,
                    in_kg=self._quantize(in_q),
                    out_kg=self._quantize(out_q),
                )
                for bucket, in_q, out_q in movement_rows
            ],
            stock_by_company=[
                StockByCompany(company_name=name, total_qty=self._quantize(qty))
                for name, qty in stock_by_company
            ],
            top_consumed=top_consumed,
            dead_stock=dead_stock,
        )

    async def adhesives_overview(
        self,
        *,
        range_params: DashboardRange,
        permissions: frozenset[str],
    ) -> AdhesivesDashboard:
        date_from, date_to, weekly = self._resolve_range(range_params)
        can_view_price = has_permission(permissions, ADHESIVE_VIEW_PRICE)

        lines = await self.repo.list_active_adhesive_lines()
        active_lines = len(lines)
        total_qty = sum((Decimal(line.total_qty or 0) for line in lines), Decimal("0"))
        out_of_stock = sum(
            1 for line in lines if (line.total_qty or Decimal("0")) <= 0
        )

        stock_value = Decimal("0")
        valued_count = 0
        if can_view_price:
            for line in lines:
                qty = Decimal(line.total_qty or 0)
                rate = line.adhesive_rate
                if qty > 0 and rate is not None:
                    stock_value += qty * Decimal(rate)
                    valued_count += 1

        movement_rows = await self.repo.adhesive_movement_buckets(
            date_from=date_from,
            date_to=date_to,
            weekly=weekly,
        )
        stock_by_company = await self.repo.adhesive_stock_qty_by_company()
        out_by_line = await self.repo.adhesive_line_out_qty_in_range(
            date_from=date_from,
            date_to=date_to,
        )

        line_labels: dict[UUID, str] = {}
        brand_ids = {line.brand_id for line in lines}
        code_ids = {line.adhesive_code_id for line in lines}
        if brand_ids:
            brand_rows = await self.session.execute(
                select(AdhesiveBrand).where(AdhesiveBrand.id.in_(brand_ids))
            )
            brands = {row.id: row.name for row in brand_rows.scalars()}
        else:
            brands = {}
        if code_ids:
            code_rows = await self.session.execute(
                select(AdhesiveCode).where(AdhesiveCode.id.in_(code_ids))
            )
            codes = {row.id: row.code for row in code_rows.scalars()}
        else:
            codes = {}
        for line in lines:
            line_labels[line.id] = (
                f"{brands.get(line.brand_id, '')} · {codes.get(line.adhesive_code_id, '')}"
            )

        top_consumed: list[TopConsumedAdhesiveLine] = []
        for line_id, out_qty in sorted(out_by_line.items(), key=lambda pair: pair[1], reverse=True)[:5]:
            name = line_labels.get(line_id)
            if name is None:
                continue
            top_consumed.append(
                TopConsumedAdhesiveLine(
                    adhesive_line_id=str(line_id),
                    name=name,
                    out_qty=self._quantize(out_qty),
                )
            )

        return AdhesivesDashboard(
            date_from=date_from,
            date_to=date_to,
            kpis=AdhesivesDashboardKpis(
                active_lines=active_lines,
                total_qty_on_hand=self._quantize(total_qty),
                out_of_stock_lines=out_of_stock,
                stock_value=self._quantize(stock_value) if can_view_price else None,
                valued_line_count=valued_count if can_view_price else 0,
            ),
            movement_buckets=[
                MovementActivityBucket(
                    bucket_start=bucket,
                    in_kg=self._quantize(in_q),
                    out_kg=self._quantize(out_q),
                )
                for bucket, in_q, out_q in movement_rows
            ],
            stock_by_company=[
                StockByCompany(company_name=name, total_qty=self._quantize(qty))
                for name, qty in stock_by_company
            ],
            top_consumed=top_consumed,
        )
