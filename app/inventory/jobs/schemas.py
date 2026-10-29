"""Jobs and cylinder returns API schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.schemas.related_documents import RelatedDocumentRef
from app.core.enums import JobStatus


class JobCylinderInput(BaseModel):
    width: Decimal = Field(gt=0)
    circumference: Decimal = Field(gt=0)


class JobColorInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class JobFileMeta(BaseModel):
    filename: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None


class JobCylinderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    width: Decimal
    circumference: Decimal


class JobColorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    name: str


class JobPauseResponse(BaseModel):
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


class JobCreate(BaseModel):
    company_id: UUID
    product_name: str = Field(min_length=1, max_length=200)
    cylinder_count: int = Field(ge=1, le=50)
    cylinders: list[JobCylinderInput]
    color_count: int | None = Field(default=None, ge=0, le=50)
    colors: list[JobColorInput] = Field(default_factory=list)
    pet_size: str | None = Field(default=None, max_length=100)
    cylinder_cost: Decimal | None = Field(default=None, ge=0)
    cylinder_location: str | None = Field(default=None, max_length=200)
    remarks: str | None = None
    status: JobStatus = JobStatus.ACTIVE

    @model_validator(mode="after")
    def validate_children(self) -> JobCreate:
        if len(self.cylinders) != self.cylinder_count:
            raise ValueError("cylinders length must match cylinder_count")
        count = self.color_count if self.color_count is not None else len(self.colors)
        if self.color_count is not None and len(self.colors) != count:
            raise ValueError("colors length must match color_count")
        if self.status in (JobStatus.RETURNED, JobStatus.PAUSED, JobStatus.RESUMED):
            raise ValueError("status cannot be set to RETURNED, PAUSED, or RESUMED on create")
        return self


class JobUpdate(BaseModel):
    company_id: UUID | None = None
    product_name: str | None = Field(default=None, min_length=1, max_length=200)
    cylinder_count: int | None = Field(default=None, ge=1, le=50)
    cylinders: list[JobCylinderInput] | None = None
    color_count: int | None = Field(default=None, ge=0, le=50)
    colors: list[JobColorInput] | None = None
    pet_size: str | None = Field(default=None, max_length=100)
    cylinder_cost: Decimal | None = None
    cylinder_location: str | None = Field(default=None, max_length=200)
    remarks: str | None = None
    status: JobStatus | None = None

    @model_validator(mode="after")
    def validate_children(self) -> JobUpdate:
        if self.status in (JobStatus.RETURNED, JobStatus.PAUSED):
            raise ValueError("status cannot be set to RETURNED or PAUSED via update")
        if self.cylinder_count is not None and self.cylinders is not None:
            if len(self.cylinders) != self.cylinder_count:
                raise ValueError("cylinders length must match cylinder_count")
        if self.color_count is not None and self.colors is not None:
            if len(self.colors) != self.color_count:
                raise ValueError("colors length must match color_count")
        return self


class JobFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "job_number", "product_name", "status"}
    )

    status: JobStatus | None = None
    company_id: UUID | None = None
    include_closed: bool = False


class JobListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_number: str
    company_id: UUID
    company_name: str
    product_name: str
    cylinder_count: int
    color_count: int | None
    pet_size: str | None
    cylinder_cost: Decimal | None = None
    cylinder_location: str | None
    status: JobStatus
    created_at: datetime
    updated_at: datetime


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_number: str
    company_id: UUID
    company_name: str
    product_name: str
    cylinder_count: int
    color_count: int | None
    pet_size: str | None
    cylinder_cost: Decimal | None = None
    cylinder_location: str | None
    remarks: str | None
    status: JobStatus
    cylinders: list[JobCylinderResponse]
    colors: list[JobColorResponse]
    pauses: list[JobPauseResponse] = Field(default_factory=list)
    job_image: JobFileMeta | None = None
    challan: JobFileMeta | None = None
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class JobPauseRequest(BaseModel):
    pause_remarks: str | None = None


class JobResumeRequest(BaseModel):
    resume_remarks: str | None = None


class CylinderReturnCreate(BaseModel):
    job_id: UUID
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
    job_id: UUID | None = None


class CylinderReturnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    return_number: str
    job_id: UUID
    job_number: str
    company_id: UUID
    company_name: str
    remarks: str | None
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


JOB_FILE_SLOTS = frozenset({"job_image", "challan"})
