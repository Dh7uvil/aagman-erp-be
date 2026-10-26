"""Inventory request and response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import MaterialMovementDirection


def _decimal_non_negative(value: Decimal) -> Decimal:
    if value < 0:
        raise ValueError("must be zero or greater")
    return value


class UnitCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    is_active: bool = True


class UnitUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class UnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UnitFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at", "name", "code"})

    is_active: bool | None = None


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    is_active: bool = True


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CategoryFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at", "name"})

    is_active: bool | None = None
    roots_only: bool | None = None


class MicronCreate(BaseModel):
    product_id: UUID
    name: str = Field(min_length=1, max_length=200)
    price_per_unit: Decimal | None = None
    price_unit_id: UUID | None = None
    is_active: bool = True


class MicronUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    price_per_unit: Decimal | None = None
    price_unit_id: UUID | None = None
    is_active: bool | None = None


class MicronResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    product_name: str
    name: str
    price_per_unit: Decimal | None = None
    price_unit_id: UUID | None = None
    price_unit_code: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MicronFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at", "name"})

    product_id: UUID | None = None
    is_active: bool | None = None


class MaterialCreate(BaseModel):
    parent_id: UUID
    unit_id: UUID | None = None
    size: Decimal
    size_unit_id: UUID | None = None
    name: str | None = Field(default=None, max_length=200)
    opening_rolls: Decimal = Field(default=Decimal("0"))
    opening_kg: Decimal = Field(default=Decimal("0"))
    is_active: bool = True

    @field_validator("size")
    @classmethod
    def validate_size(cls, value: Decimal) -> Decimal:
        return _decimal_non_negative(value)

    @field_validator("opening_rolls", "opening_kg")
    @classmethod
    def validate_opening_non_negative(cls, value: Decimal) -> Decimal:
        return _decimal_non_negative(value)


class MaterialUpdate(BaseModel):
    parent_id: UUID | None = None
    unit_id: UUID | None = None
    size: Decimal | None = None
    size_unit_id: UUID | None = None
    name: str | None = Field(default=None, max_length=200)
    rolls_on_hand: Decimal | None = None
    total_kg: Decimal | None = None
    is_active: bool | None = None

    @field_validator("size")
    @classmethod
    def validate_size(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return value
        return _decimal_non_negative(value)

    @field_validator("rolls_on_hand", "total_kg")
    @classmethod
    def validate_stock_non_negative(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return value
        return _decimal_non_negative(value)


class MaterialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    product_name: str
    micron_id: UUID
    micron_name: str
    size: Decimal
    size_unit_id: UUID
    size_unit_code: str
    size_label: str
    unit_id: UUID | None = None
    unit_code: str = ""
    unit_name: str = ""
    name: str
    rolls_on_hand: Decimal
    total_kg: Decimal
    price_per_unit: Decimal | None = None
    price_unit_id: UUID | None = None
    price_unit_code: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MaterialFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at", "name", "size"})

    parent_id: UUID | None = None
    product_id: UUID | None = None
    is_active: bool | None = None
    size: Decimal | None = None
    rolls: Decimal | None = None
    kg_lt: Decimal | None = None
    kg_gt: Decimal | None = None

    @field_validator("size", "rolls", "kg_lt", "kg_gt")
    @classmethod
    def validate_material_numeric_filters(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("must be zero or greater")
        return value


class MovementCreate(BaseModel):
    category_id: UUID
    movement_date: date
    direction: MaterialMovementDirection
    rolls: Decimal
    kilograms: Decimal
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: MaterialMovementDirection) -> MaterialMovementDirection:
        if value == MaterialMovementDirection.OPENING:
            raise ValueError("opening balances are set when creating a material")
        return value

    @field_validator("rolls", "kilograms")
    @classmethod
    def validate_qty_non_negative(cls, value: Decimal) -> Decimal:
        return _decimal_non_negative(value)


class MovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category_id: UUID
    product_name: str
    micron_name: str
    size_label: str
    category_name: str
    parent_name: str
    movement_date: date
    direction: MaterialMovementDirection
    rolls: Decimal
    kilograms: Decimal
    note: str | None
    created_by: UUID | None
    created_by_name: str | None
    created_at: datetime


class MovementFilter(BaseFilter):
    movement_date: date | None = None
    category_id: UUID | None = None


class DayReportRow(BaseModel):
    category_id: UUID
    product_id: UUID
    product_name: str
    micron_id: UUID
    micron_name: str
    size: Decimal
    size_unit_code: str
    size_label: str
    category_name: str
    parent_name: str
    unit_code: str
    in_rolls: Decimal
    in_kg: Decimal
    out_rolls: Decimal
    out_kg: Decimal
    closing_rolls: Decimal
    closing_kg: Decimal
    price_per_unit: Decimal | None = None
    price_unit_code: str | None = None
