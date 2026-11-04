"""Ink inventory request and response schemas."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import MaterialMovementDirection

_HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

INK_FILE_SLOTS = frozenset({"product_image", "ink_image"})


def _normalize_hex(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if not _HEX_PATTERN.match(trimmed):
        raise ValueError("Enter a valid hex code like #FF5733")
    return trimmed.upper()


class InkColorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    hex_code: str | None = None
    is_active: bool = True

    @field_validator("hex_code", mode="before")
    @classmethod
    def validate_hex(cls, value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError("Invalid hex code")
        return _normalize_hex(value)


class InkColorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    hex_code: str | None = None
    is_active: bool | None = None

    @field_validator("hex_code", mode="before")
    @classmethod
    def validate_hex(cls, value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError("Invalid hex code")
        return _normalize_hex(value)


class InkColorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    hex_code: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class InkColorFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at", "name"})

    is_active: bool | None = None


class InkBrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    is_active: bool = True


class InkBrandUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class InkBrandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class InkBrandFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at", "name"})

    is_active: bool | None = None


class InkFileMeta(BaseModel):
    filename: str
    content_type: str
    size_bytes: int


class InkLineResponse(BaseModel):
    id: UUID
    brand_id: UUID
    brand_name: str
    color_id: UUID
    color_name: str
    hex_code: str | None
    drum_count: Decimal
    drum_qty: Decimal
    drum_unit_id: UUID
    drum_unit_code: str
    total_qty: Decimal
    ink_rate: Decimal | None = None
    total_rate: Decimal | None = None
    created_at: datetime
    updated_at: datetime


class InkLineUpsert(BaseModel):
    id: UUID | None = None
    brand_id: UUID
    color_id: UUID
    drum_count: Decimal = Field(default=Decimal("0"))
    drum_qty: Decimal = Field(default=Decimal("0"))
    drum_unit_id: UUID | None = None
    ink_rate: Decimal | None = None

    @field_validator("drum_count", "drum_qty", mode="before")
    @classmethod
    def decimal_fields(cls, value: object) -> Decimal:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))


class InkSheetCreate(BaseModel):
    company_id: UUID
    lines: list[InkLineUpsert] = Field(default_factory=list)


class InkSheetUpdate(BaseModel):
    lines: list[InkLineUpsert] | None = None


class InkSheetListItem(BaseModel):
    id: UUID
    company_id: UUID
    company_name: str
    line_count: int
    total_drums: Decimal
    total_qty: Decimal
    created_at: datetime
    updated_at: datetime


class InkLineListItem(BaseModel):
    id: UUID
    ink_sheet_id: UUID
    company_id: UUID
    company_name: str
    brand_id: UUID
    brand_name: str
    color_id: UUID
    color_name: str
    hex_code: str | None
    drum_count: Decimal
    drum_qty: Decimal
    drum_unit_id: UUID
    drum_unit_code: str
    total_qty: Decimal
    ink_rate: Decimal | None = None
    total_rate: Decimal | None = None
    created_at: datetime
    updated_at: datetime


class InkSheetResponse(BaseModel):
    id: UUID
    company_id: UUID
    company_name: str
    lines: list[InkLineResponse]
    product_image: InkFileMeta | None = None
    ink_image: InkFileMeta | None = None
    created_at: datetime
    updated_at: datetime


class InkSheetFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at"})

    company_id: UUID | None = None


class InkStockOutCreate(BaseModel):
    ink_line_id: UUID
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


class InkColorUsageLine(BaseModel):
    ink_line_id: UUID
    ink_sheet_id: UUID
    company_id: UUID
    company_name: str
    brand_id: UUID
    brand_name: str
    drum_count: Decimal
    drum_qty: Decimal
    drum_unit_code: str
    total_qty: Decimal
    ink_rate: Decimal | None = None
    total_rate: Decimal | None = None


class InkColorUsageResponse(BaseModel):
    color: InkColorResponse
    companies_with_stock: int
    lines: list[InkColorUsageLine]


class InkDayReportRow(BaseModel):
    ink_line_id: UUID
    ink_sheet_id: UUID
    company_id: UUID
    company_name: str
    brand_id: UUID
    brand_name: str
    color_id: UUID
    color_name: str
    hex_code: str | None
    drum_unit_code: str
    in_drums: Decimal
    in_qty: Decimal
    out_drums: Decimal
    out_qty: Decimal
    closing_drums: Decimal
    closing_qty: Decimal
    ink_rate: Decimal | None = None


class InkMovementCreate(BaseModel):
    ink_line_id: UUID
    movement_date: date
    direction: MaterialMovementDirection
    drums: Decimal
    quantity: Decimal
    note: str | None = None
