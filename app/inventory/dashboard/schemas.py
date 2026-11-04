"""Dashboard response schemas."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DashboardRange(BaseModel):
    """Optional inclusive date range; defaults to the last 30 days ending today."""

    model_config = ConfigDict(extra="forbid")

    date_from: date | None = None
    date_to: date | None = None


class CylinderStatusCount(BaseModel):
    status: str
    count: int


class CylinderActivityBucket(BaseModel):
    bucket_start: date
    cylinders_created: int
    returns_created: int


class TopCompanyCylinders(BaseModel):
    company_id: str
    company_name: str
    active_cylinders: int
    cylinder_count: int


class OpenCylinderPause(BaseModel):
    cylinder_id: str
    cylinder_number: str
    company_name: str
    paused_at: datetime
    days_paused: int


class CylindersDashboardKpis(BaseModel):
    active_cylinders: int
    paused_cylinders: int
    cylinders_in_circulation: int
    awaiting_return: int
    cylinder_cost_exposure: Decimal | None = None


class CylindersDashboard(BaseModel):
    date_from: date
    date_to: date
    kpis: CylindersDashboardKpis
    status_breakdown: list[CylinderStatusCount]
    activity_buckets: list[CylinderActivityBucket]
    top_companies: list[TopCompanyCylinders]
    open_pauses: list[OpenCylinderPause] = Field(default_factory=list)


class MovementActivityBucket(BaseModel):
    bucket_start: date
    in_kg: Decimal
    out_kg: Decimal


class StockByProduct(BaseModel):
    product_name: str
    total_kg: Decimal


class ReorderWatchItem(BaseModel):
    material_id: str
    name: str
    total_kg: Decimal
    avg_daily_out_kg: Decimal
    days_of_cover: Decimal


class TopConsumedSku(BaseModel):
    material_id: str
    name: str
    out_kg: Decimal


class DeadStockItem(BaseModel):
    material_id: str
    name: str
    total_kg: Decimal
    days_idle: int
    last_activity_date: date


class MaterialsDashboardKpis(BaseModel):
    active_skus: int
    total_kg_on_hand: Decimal
    out_of_stock_skus: int
    stock_value: Decimal | None = None
    valued_sku_count: int = 0
    dead_stock_skus: int = 0


class MaterialsDashboard(BaseModel):
    date_from: date
    date_to: date
    kpis: MaterialsDashboardKpis
    movement_buckets: list[MovementActivityBucket]
    stock_by_product: list[StockByProduct]
    reorder_watchlist: list[ReorderWatchItem]
    top_consumed: list[TopConsumedSku]
    dead_stock: list[DeadStockItem] = Field(default_factory=list)


class StockByCompany(BaseModel):
    company_name: str
    total_qty: Decimal


class TopConsumedInkLine(BaseModel):
    ink_line_id: str
    name: str
    out_qty: Decimal


class InkDeadStockItem(BaseModel):
    ink_line_id: str
    name: str
    total_qty: Decimal
    days_idle: int
    last_activity_date: date


class InksDashboardKpis(BaseModel):
    active_lines: int
    total_qty_on_hand: Decimal
    out_of_stock_lines: int
    stock_value: Decimal | None = None
    valued_line_count: int = 0
    dead_stock_lines: int = 0


class InksDashboard(BaseModel):
    date_from: date
    date_to: date
    kpis: InksDashboardKpis
    movement_buckets: list[MovementActivityBucket]
    stock_by_company: list[StockByCompany]
    top_consumed: list[TopConsumedInkLine]
    dead_stock: list[InkDeadStockItem] = Field(default_factory=list)
