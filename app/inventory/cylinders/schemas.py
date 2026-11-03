"""Jobs and cylinder returns API schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.schemas.related_documents import RelatedDocumentRef
from app.common.utils.validators import normalize_required_text
from app.core.enums import CylinderStatus


class CylinderSizeInput(BaseModel):
    width: Decimal = Field(gt=0)
    circumference: Decimal = Field(gt=0)


class CylinderColorInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class CylinderFileMeta(BaseModel):
    filename: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None


class CylinderSizeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    width: Decimal
    circumference: Decimal


class CylinderColorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    name: str


class CylinderPauseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    paused_at: datetime
    paused_by: UUID | None
    paused_by_name: str | None = None
    pause_remarks: str | None
    resumed_at: datetime | None
    resumed_by: UUID | None
    resumed_by_name: str | None = None
    resume_remarks: str | None


class CylinderCreate(BaseModel):
    company_id: UUID
    product_name: str = Field(min_length=1, max_length=200)
    cylinder_count: int = Field(ge=1, le=50)
    cylinders: list[CylinderSizeInput]
    color_count: int | None = Field(default=None, ge=0, le=50)
    colors: list[CylinderColorInput] = Field(default_factory=list)
    pet_size: str = Field(min_length=1, max_length=100)
    cylinder_cost: Decimal | None = Field(default=None, ge=0)
    cylinder_location: str | None = Field(default=None, max_length=200)
    remarks: str | None = None
    status: CylinderStatus = CylinderStatus.ACTIVE

    @field_validator("pet_size")
    @classmethod
    def normalize_pet_size(cls, value: str) -> str:
        return normalize_required_text(value, field_name="pet_size")

    @model_validator(mode="after")
    def validate_children(self) -> CylinderCreate:
        if len(self.cylinders) != self.cylinder_count:
            raise ValueError("cylinders length must match cylinder_count")
        count = self.color_count if self.color_count is not None else len(self.colors)
        if self.color_count is not None and len(self.colors) != count:
            raise ValueError("colors length must match color_count")
        if self.status in (CylinderStatus.RETURNED, CylinderStatus.PAUSED):
            raise ValueError("status cannot be set to RETURNED or PAUSED on create")
        return self


class CylinderUpdate(BaseModel):
    company_id: UUID | None = None
    product_name: str | None = Field(default=None, min_length=1, max_length=200)
    cylinder_count: int | None = Field(default=None, ge=1, le=50)
    cylinders: list[CylinderSizeInput] | None = None
    color_count: int | None = Field(default=None, ge=0, le=50)
    colors: list[CylinderColorInput] | None = None
    pet_size: str | None = Field(default=None, min_length=1, max_length=100)
    cylinder_cost: Decimal | None = None
    cylinder_location: str | None = Field(default=None, max_length=200)
    remarks: str | None = None
    status: CylinderStatus | None = None

    @field_validator("pet_size")
    @classmethod
    def normalize_pet_size(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="pet_size")

    @model_validator(mode="after")
    def validate_children(self) -> CylinderUpdate:
        if self.status in (CylinderStatus.RETURNED, CylinderStatus.PAUSED):
            raise ValueError("status cannot be set to RETURNED or PAUSED via update")
        if self.cylinder_count is not None and self.cylinders is not None:
            if len(self.cylinders) != self.cylinder_count:
                raise ValueError("cylinders length must match cylinder_count")
        if self.color_count is not None and self.colors is not None:
            if len(self.colors) != self.color_count:
                raise ValueError("colors length must match color_count")
        return self


class CylinderFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "cylinder_number", "product_name", "status"}
    )

    status: CylinderStatus | None = None
    company_id: UUID | None = None
    include_closed: bool = False


class CylinderListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cylinder_number: str
    company_id: UUID
    company_name: str
    product_name: str
    cylinder_count: int
    color_count: int | None
    pet_size: str | None
    cylinder_cost: Decimal | None = None
    cylinder_location: str | None
    status: CylinderStatus
    cylinder_image: CylinderFileMeta | None = None
    created_at: datetime
    updated_at: datetime


class CylinderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cylinder_number: str
    company_id: UUID
    company_name: str
    product_name: str
    cylinder_count: int
    color_count: int | None
    pet_size: str | None
    cylinder_cost: Decimal | None = None
    cylinder_location: str | None
    remarks: str | None
    status: CylinderStatus
    cylinders: list[CylinderSizeResponse]
    colors: list[CylinderColorResponse]
    pauses: list[CylinderPauseResponse] = Field(default_factory=list)
    cylinder_image: CylinderFileMeta | None = None
    challan: CylinderFileMeta | None = None
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CylinderPauseRequest(BaseModel):
    pause_remarks: str | None = None


class CylinderResumeRequest(BaseModel):
    resume_remarks: str | None = None


class CylinderReturnCreate(BaseModel):
    cylinder_id: UUID
    company_id: UUID
    remarks: str | None = None


class CylinderReturnUpdate(BaseModel):
    company_id: UUID | None = None
    remarks: str | None = None


class CylinderReturnFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "return_number"}
    )

    company_id: UUID | None = None
    cylinder_id: UUID | None = None


class CylinderReturnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    return_number: str
    cylinder_id: UUID
    cylinder_number: str
    company_id: UUID
    company_name: str
    company_gst_number: str | None = None
    company_address: str | None = None
    product_name: str
    cylinder_count: int
    remarks: str | None
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


CYLINDER_FILE_SLOTS = frozenset({"cylinder_image", "challan"})
