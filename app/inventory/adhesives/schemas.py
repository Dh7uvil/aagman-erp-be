"""Adhesive inventory request and response schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import MaterialMovementDirection


class AdhesiveCodeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=200)
    is_active: bool = True


class AdhesiveCodeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class AdhesiveCodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AdhesiveCodeFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at", "code"})

    is_active: bool | None = None


class AdhesiveBrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    is_active: bool = True


class AdhesiveBrandUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class AdhesiveBrandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AdhesiveBrandFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at", "name"})

    is_active: bool | None = None


class AdhesiveLineResponse(BaseModel):
    id: UUID
    brand_id: UUID
    brand_name: str
    adhesive_code_id: UUID
    code: str
    drum_count: Decimal
    drum_qty: Decimal
    drum_unit_id: UUID
    drum_unit_code: str
    total_qty: Decimal
    adhesive_rate: Decimal | None = None
    total_rate: Decimal | None = None
    avg_price_per_unit: Decimal | None = None
    price_unit_code: str | None = None
    created_at: datetime
    updated_at: datetime


class AdhesiveLineUpsert(BaseModel):
    id: UUID | None = None
    brand_id: UUID
    adhesive_code_id: UUID
    drum_count: Decimal = Field(default=Decimal("0"))
    drum_qty: Decimal = Field(default=Decimal("0"))
    drum_unit_id: UUID | None = None
    adhesive_rate: Decimal | None = None

    @field_validator("drum_count", "drum_qty", mode="before")
    @classmethod
    def decimal_fields(cls, value: object) -> Decimal:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))


class AdhesiveSheetCreate(BaseModel):
    company_id: UUID
    lines: list[AdhesiveLineUpsert] = Field(default_factory=list)


class AdhesiveSheetUpdate(BaseModel):
    lines: list[AdhesiveLineUpsert] | None = None


class AdhesiveSheetListItem(BaseModel):
    id: UUID
    company_id: UUID
    company_name: str
    line_count: int
    total_drums: Decimal
    total_qty: Decimal
    created_at: datetime
    updated_at: datetime


class AdhesiveLineListItem(BaseModel):
    id: UUID
    adhesive_sheet_id: UUID
    company_id: UUID
    company_name: str
    brand_id: UUID
    brand_name: str
    adhesive_code_id: UUID
    code: str
    drum_count: Decimal
    drum_qty: Decimal
    drum_unit_id: UUID
    drum_unit_code: str
    total_qty: Decimal
    adhesive_rate: Decimal | None = None
    total_rate: Decimal | None = None
    created_at: datetime
    updated_at: datetime


class AdhesiveSheetResponse(BaseModel):
    id: UUID
    company_id: UUID
    company_name: str
    lines: list[AdhesiveLineResponse]
    created_at: datetime
    updated_at: datetime


class AdhesiveSheetFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at"})

    company_id: UUID | None = None


class AdhesiveStockOutCreate(BaseModel):
    adhesive_line_id: UUID
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


class AdhesiveCodeUsageLine(BaseModel):
    adhesive_line_id: UUID
    adhesive_sheet_id: UUID
    company_id: UUID
    company_name: str
    brand_id: UUID
    brand_name: str
    drum_count: Decimal
    drum_qty: Decimal
    drum_unit_code: str
    total_qty: Decimal
    adhesive_rate: Decimal | None = None
    total_rate: Decimal | None = None
    avg_price_per_unit: Decimal | None = None
    price_unit_code: str | None = None


class AdhesiveCodeUsageResponse(BaseModel):
    adhesive_code: AdhesiveCodeResponse
    companies_with_stock: int
    lines: list[AdhesiveCodeUsageLine]


class AdhesiveDayReportRow(BaseModel):
    adhesive_line_id: UUID
    adhesive_sheet_id: UUID
    company_id: UUID
    company_name: str
    brand_id: UUID
    brand_name: str
    adhesive_code_id: UUID
    code: str
    drum_unit_code: str
    in_drums: Decimal
    in_qty: Decimal
    out_drums: Decimal
    out_qty: Decimal
    closing_drums: Decimal
    closing_qty: Decimal
    adhesive_rate: Decimal | None = None


class AdhesiveMovementCreate(BaseModel):
    adhesive_line_id: UUID
    movement_date: date
    direction: MaterialMovementDirection
    drums: Decimal
    quantity: Decimal
    note: str | None = None
