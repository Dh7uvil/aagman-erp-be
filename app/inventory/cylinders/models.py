"""Jobs and cylinder returns ORM models."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import CylinderStatus
from app.db.base import SoftDeleteModel, TimestampedModel
from app.db.mixins import AuditUserMixin


class Cylinder(AuditUserMixin, SoftDeleteModel):
    __tablename__ = "cylinders"
    __table_args__ = (
        Index(
            "uq_cylinders_cylinder_number_active",
            "cylinder_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_cylinders_company_id", "company_id"),
        Index("ix_cylinders_status", "status"),
    )

    cylinder_number: Mapped[str] = mapped_column(String(30), nullable=False)
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

    cylinder_image_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cylinder_image_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cylinder_image_content_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    cylinder_image_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    challan_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    challan_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    challan_content_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    challan_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    @property
    def status_enum(self) -> CylinderStatus:
        return CylinderStatus(self.status)


class CylinderSize(TimestampedModel):
    __tablename__ = "cylinder_sizes"
    __table_args__ = (
        Index(
            "uq_cylinder_sizes_cylinder_position",
            "cylinder_id",
            "position",
            unique=True,
        ),
    )

    cylinder_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("cylinders.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    circumference: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)


class CylinderColor(TimestampedModel):
    __tablename__ = "cylinder_colors"
    __table_args__ = (
        Index(
            "uq_cylinder_colors_cylinder_position",
            "cylinder_id",
            "position",
            unique=True,
        ),
    )

    cylinder_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("cylinders.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class CylinderPause(TimestampedModel):
    __tablename__ = "cylinder_pauses"
    __table_args__ = (
        Index(
            "uq_cylinder_pauses_open",
            "cylinder_id",
            unique=True,
            postgresql_where=text("resumed_at IS NULL"),
        ),
    )

    cylinder_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("cylinders.id", ondelete="CASCADE"),
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
            "uq_cylinder_returns_cylinder_active",
            "cylinder_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    return_number: Mapped[str] = mapped_column(String(30), nullable=False)
    cylinder_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("cylinders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
