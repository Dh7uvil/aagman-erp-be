"""Solvent inventory request and response schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import MaterialMovementDirection


class SolventNameCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    is_active: bool = True


class SolventNameUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class SolventNameResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SolventNameFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at", "name"})

    is_active: bool | None = None


class SolventBrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    is_active: bool = True


class SolventBrandUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class SolventBrandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SolventBrandFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at", "name"})

    is_active: bool | None = None


class SolventLineResponse(BaseModel):
    id: UUID
    brand_id: UUID
    brand_name: str
    solvent_name_id: UUID
    name: str
    drum_count: Decimal
    drum_qty: Decimal
    drum_unit_id: UUID
    drum_unit_code: str
    total_qty: Decimal
    solvent_rate: Decimal | None = None
    total_rate: Decimal | None = None
    avg_price_per_unit: Decimal | None = None
    price_unit_code: str | None = None
    created_at: datetime
    updated_at: datetime


class SolventLineUpsert(BaseModel):
    id: UUID | None = None
    brand_id: UUID
    solvent_name_id: UUID
    drum_count: Decimal = Field(default=Decimal("0"))
    drum_qty: Decimal = Field(default=Decimal("0"))
    drum_unit_id: UUID | None = None
    solvent_rate: Decimal | None = None

    @field_validator("drum_count", "drum_qty", mode="before")
    @classmethod
    def decimal_fields(cls, value: object) -> Decimal:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))


class SolventSheetCreate(BaseModel):
    company_id: UUID
    lines: list[SolventLineUpsert] = Field(default_factory=list)


class SolventSheetUpdate(BaseModel):
    lines: list[SolventLineUpsert] | None = None


class SolventSheetListItem(BaseModel):
    id: UUID
    company_id: UUID
    company_name: str
    line_count: int
    total_drums: Decimal
    total_qty: Decimal
    created_at: datetime
    updated_at: datetime


class SolventLineListItem(BaseModel):
    id: UUID
    solvent_sheet_id: UUID
    company_id: UUID
    company_name: str
    brand_id: UUID
    brand_name: str
    solvent_name_id: UUID
    name: str
    drum_count: Decimal
    drum_qty: Decimal
    drum_unit_id: UUID
    drum_unit_code: str
    total_qty: Decimal
    solvent_rate: Decimal | None = None
    total_rate: Decimal | None = None
    created_at: datetime
    updated_at: datetime


class SolventSheetResponse(BaseModel):
    id: UUID
    company_id: UUID
    company_name: str
    lines: list[SolventLineResponse]
    created_at: datetime
    updated_at: datetime


class SolventSheetFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at"})

    company_id: UUID | None = None


class SolventStockOutCreate(BaseModel):
    solvent_line_id: UUID
    movement_date: date | None = None
    drums: Decimal = Field(default=Decimal("0"))
    quantity: Decimal = Field(default=Decimal("0"))
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_amount(self) -> Self:
        if self.drums == 0 and self.quantity == 0:
            raise ValueError("Enter drums and/or quantity to remove")
        if self.drums < 0 or self.quantity < 0:
            raise ValueError("Amounts must be zero or greater")
        return self


class SolventNameUsageLine(BaseModel):
    solvent_line_id: UUID
    solvent_sheet_id: UUID
    company_id: UUID
    company_name: str
    brand_id: UUID
    brand_name: str
    drum_count: Decimal
    drum_qty: Decimal
    drum_unit_code: str
    total_qty: Decimal
    solvent_rate: Decimal | None = None
    total_rate: Decimal | None = None
    avg_price_per_unit: Decimal | None = None
    price_unit_code: str | None = None


class SolventNameUsageResponse(BaseModel):
    solvent_name: SolventNameResponse
    companies_with_stock: int
    lines: list[SolventNameUsageLine]


class SolventDayReportRow(BaseModel):
    solvent_line_id: UUID
    solvent_sheet_id: UUID
    company_id: UUID
    company_name: str
    brand_id: UUID
    brand_name: str
    solvent_name_id: UUID
    name: str
    drum_unit_code: str
    in_drums: Decimal
    in_qty: Decimal
    out_drums: Decimal
    out_qty: Decimal
    closing_drums: Decimal
    closing_qty: Decimal
    solvent_rate: Decimal | None = None


class SolventMovementCreate(BaseModel):
    solvent_line_id: UUID
    movement_date: date
    direction: MaterialMovementDirection
    drums: Decimal
    quantity: Decimal
    note: str | None = None
