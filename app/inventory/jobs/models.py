"""Jobs and cylinder returns ORM models."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import JobStatus
from app.db.base import SoftDeleteModel, TimestampedModel
from app.db.mixins import AuditUserMixin


class Job(AuditUserMixin, SoftDeleteModel):
    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "uq_jobs_job_number_active",
            "job_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_jobs_company_id", "company_id"),
        Index("ix_jobs_status", "status"),
    )

    job_number: Mapped[str] = mapped_column(String(30), nullable=False)
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    cylinder_count: Mapped[int] = mapped_column(Integer, nullable=False)
    color_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pet_size: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cylinder_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    cylinder_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'ACTIVE'"),
    )

    job_image_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    job_image_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_image_content_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    job_image_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    challan_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    challan_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    challan_content_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    challan_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    @property
    def status_enum(self) -> JobStatus:
        return JobStatus(self.status)


class JobCylinder(TimestampedModel):
    __tablename__ = "job_cylinders"
    __table_args__ = (
        Index(
            "uq_job_cylinders_job_position",
            "job_id",
            "position",
            unique=True,
        ),
    )

    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    circumference: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)


class JobColor(TimestampedModel):
    __tablename__ = "job_colors"
    __table_args__ = (
        Index(
            "uq_job_colors_job_position",
            "job_id",
            "position",
            unique=True,
        ),
    )

    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class JobPause(TimestampedModel):
    __tablename__ = "job_pauses"
    __table_args__ = (
        Index(
            "uq_job_pauses_open",
            "job_id",
            unique=True,
            postgresql_where=text("resumed_at IS NULL"),
        ),
    )

    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    paused_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paused_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    pause_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resumed_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resume_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)


class CylinderReturn(AuditUserMixin, SoftDeleteModel):
    __tablename__ = "cylinder_returns"
    __table_args__ = (
        Index(
            "uq_cylinder_returns_return_number_active",
            "return_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_cylinder_returns_job_active",
            "job_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    return_number: Mapped[str] = mapped_column(String(30), nullable=False)
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
