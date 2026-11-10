"""Ink inventory ORM models."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import MaterialMovementDirection
from app.db.base import SoftDeleteModel
from app.db.mixins import AuditUserMixin, IsActiveMixin


class InkColor(IsActiveMixin, SoftDeleteModel):
    __tablename__ = "ink_colors"
    __table_args__ = (
        Index(
            "uq_ink_colors_name_active",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hex_code: Mapped[str | None] = mapped_column(String(7), nullable=True)


class InkBrand(IsActiveMixin, SoftDeleteModel):
    __tablename__ = "ink_brands"
    __table_args__ = (
        Index(
            "uq_ink_brands_name_active",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)


class InkSheet(AuditUserMixin, SoftDeleteModel):
    __tablename__ = "ink_sheets"
    __table_args__ = (
        Index(
            "uq_ink_sheets_company_active",
            "company_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    product_image_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    product_image_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_image_content_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    product_image_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    ink_image_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ink_image_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ink_image_content_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    ink_image_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class InkLine(SoftDeleteModel):
    __tablename__ = "ink_lines"
    __table_args__ = (
        Index(
            "uq_ink_lines_sheet_brand_color_active",
            "ink_sheet_id",
            "brand_id",
            "color_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_ink_lines_color_id", "color_id"),
        Index("ix_ink_lines_brand_id", "brand_id"),
    )

    ink_sheet_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ink_sheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    brand_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ink_brands.id", ondelete="RESTRICT"),
        nullable=False,
    )
    color_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ink_colors.id", ondelete="RESTRICT"),
        nullable=False,
    )
    drum_count: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    drum_qty: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    drum_unit_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("inventory_units.id", ondelete="RESTRICT"),
        nullable=False,
    )
    total_qty: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    ink_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    total_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)


class InkMovement(SoftDeleteModel):
    __tablename__ = "ink_movements"
    __table_args__ = (
        Index("ix_ink_movements_date", "movement_date"),
        Index("ix_ink_movements_line", "ink_line_id"),
    )

    ink_line_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ink_lines.id", ondelete="RESTRICT"),
        nullable=False,
    )
    movement_date: Mapped[date] = mapped_column(Date, nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    drums: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    ink_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    @property
    def direction_enum(self) -> MaterialMovementDirection:
        return MaterialMovementDirection(self.direction)
