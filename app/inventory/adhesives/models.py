"""Adhesive inventory ORM models."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
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


class AdhesiveCode(IsActiveMixin, SoftDeleteModel):
    __tablename__ = "adhesive_codes"
    __table_args__ = (
        Index(
            "uq_adhesive_codes_code_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    code: Mapped[str] = mapped_column(String(200), nullable=False)


class AdhesiveBrand(IsActiveMixin, SoftDeleteModel):
    __tablename__ = "adhesive_brands"
    __table_args__ = (
        Index(
            "uq_adhesive_brands_name_active",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)


class AdhesiveSheet(AuditUserMixin, SoftDeleteModel):
    __tablename__ = "adhesive_sheets"
    __table_args__ = (
        Index(
            "uq_adhesive_sheets_company_active",
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


class AdhesiveLine(SoftDeleteModel):
    __tablename__ = "adhesive_lines"
    __table_args__ = (
        Index(
            "uq_adhesive_lines_sheet_brand_code_active",
            "adhesive_sheet_id",
            "brand_id",
            "adhesive_code_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_adhesive_lines_adhesive_code_id", "adhesive_code_id"),
        Index("ix_adhesive_lines_brand_id", "brand_id"),
    )

    adhesive_sheet_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("adhesive_sheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    brand_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("adhesive_brands.id", ondelete="RESTRICT"),
        nullable=False,
    )
    adhesive_code_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("adhesive_codes.id", ondelete="RESTRICT"),
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
    adhesive_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    total_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)


class AdhesiveMovement(SoftDeleteModel):
    __tablename__ = "adhesive_movements"
    __table_args__ = (
        Index("ix_adhesive_movements_date", "movement_date"),
        Index("ix_adhesive_movements_line", "adhesive_line_id"),
    )

    adhesive_line_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("adhesive_lines.id", ondelete="RESTRICT"),
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
    adhesive_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    @property
    def direction_enum(self) -> MaterialMovementDirection:
        return MaterialMovementDirection(self.direction)
