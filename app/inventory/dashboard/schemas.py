"""Dashboard response schemas."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DashboardRange(BaseModel):
    """Optional inclusive date range; defaults to the last 30 days ending today."""

    model_config = ConfigDict(extra="forbid")

    date_from: date | None = None
    date_to: date | None = None


class JobStatusCount(BaseModel):
    status: str
    count: int


class JobActivityBucket(BaseModel):
    bucket_start: date
    jobs_created: int
    returns_created: int


class TopCompanyJobs(BaseModel):
    company_id: str
    company_name: str
    active_jobs: int
    cylinder_count: int


class OpenJobPause(BaseModel):
    job_id: str
    job_number: str
    company_name: str
    paused_at: datetime
    days_paused: int


class JobsDashboardKpis(BaseModel):
    active_jobs: int
    paused_jobs: int
    cylinders_in_circulation: int
    awaiting_return: int
    cylinder_cost_exposure: Decimal | None = None


class JobsDashboard(BaseModel):
    date_from: date
    date_to: date
    kpis: JobsDashboardKpis
    status_breakdown: list[JobStatusCount]
    activity_buckets: list[JobActivityBucket]
    top_companies: list[TopCompanyJobs]
    open_pauses: list[OpenJobPause] = Field(default_factory=list)


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


class MaterialsDashboardKpis(BaseModel):
    active_skus: int
    total_kg_on_hand: Decimal
    out_of_stock_skus: int
    stock_value: Decimal | None = None
    valued_sku_count: int = 0


class MaterialsDashboard(BaseModel):
    date_from: date
    date_to: date
    kpis: MaterialsDashboardKpis
    movement_buckets: list[MovementActivityBucket]
    stock_by_product: list[StockByProduct]
    reorder_watchlist: list[ReorderWatchItem]
    top_consumed: list[TopConsumedSku]
