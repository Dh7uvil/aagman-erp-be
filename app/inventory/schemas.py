"""Inventory request and response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import MaterialMovementDirection
from app.identity.schemas import AuditLogUserSummary


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
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "code"}
    )

    is_active: bool | None = None


class CategoryCreate(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=200)
    is_active: bool = True


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    company_id: UUID | None = None
    is_active: bool | None = None


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID | None = None
    company_name: str = ""
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CategoryFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at", "name"})

    is_active: bool | None = None
    roots_only: bool | None = None
    company_id: UUID | None = None


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
    company_id: UUID | None = None
    company_name: str = ""
    name: str
    price_per_unit: Decimal | None = None
    price_unit_id: UUID | None = None
    price_unit_code: str
    avg_price_per_unit: Decimal | None = None
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
    company_id: UUID | None = None
    company_name: str = ""
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
    avg_price_per_unit: Decimal | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MaterialFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "size"}
    )

    parent_id: UUID | None = None
    product_id: UUID | None = None
    company_id: UUID | None = None
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
    price_per_unit: Decimal | None = None
    price_unit_id: UUID | None = None

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

    @field_validator("price_per_unit")
    @classmethod
    def validate_price_non_negative(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return value
        return _decimal_non_negative(value)

    @model_validator(mode="after")
    def validate_purchase_price_on_in_only(self) -> Self:
        if self.price_per_unit is not None or self.price_unit_id is not None:
            if self.direction != MaterialMovementDirection.IN:
                raise ValueError("purchase price can only be set on incoming movements")
        return self


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


class MaterialHistoryEntry(BaseModel):
    id: UUID
    timestamp: datetime
    kind: Literal["stock", "edit"]
    action: str
    user: AuditLogUserSummary | None = None
    company_id: UUID | None = None
    company_name: str = ""
    rolls: Decimal | None = None
    kilograms: Decimal | None = None
    price_per_unit: Decimal | None = None
    price_unit_code: str | None = None
    note: str | None = None
    changes: list[dict[str, object]] = Field(default_factory=list)


class MaterialHistorySummary(BaseModel):
    company_id: UUID | None = None
    company_name: str = ""
    size_label: str
    product_name: str
    micron_name: str
    rolls_on_hand: Decimal
    total_kg: Decimal
    last_purchase_price: Decimal | None = None
    last_purchase_price_unit_code: str | None = None
    last_purchase_date: date | None = None
    last_purchase_rolls: Decimal | None = None
    avg_price_per_unit: Decimal | None = None
    price_unit_code: str | None = None


class DrumLineHistoryEntry(BaseModel):
    id: UUID
    timestamp: datetime
    kind: Literal["stock"] = "stock"
    action: str
    user: AuditLogUserSummary | None = None
    company_id: UUID | None = None
    company_name: str = ""
    drums: Decimal | None = None
    quantity: Decimal | None = None
    quantity_unit_code: str | None = None
    price_per_unit: Decimal | None = None
    price_unit_code: str | None = None
    note: str | None = None


class DrumLineHistorySummary(BaseModel):
    line_id: UUID
    sheet_id: UUID
    company_id: UUID
    company_name: str
    brand_name: str
    line_label: str
    drums_on_hand: Decimal
    total_qty: Decimal
    quantity_unit_code: str
    last_purchase_price: Decimal | None = None
    last_purchase_price_unit_code: str | None = None
    last_purchase_date: date | None = None
    last_purchase_drums: Decimal | None = None
    avg_price_per_unit: Decimal | None = None
    price_unit_code: str | None = None


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
    avg_price_per_unit: Decimal | None = None
