"""Solvent inventory ORM models."""

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


class SolventName(IsActiveMixin, SoftDeleteModel):
    __tablename__ = "solvent_names"
    __table_args__ = (
        Index(
            "uq_solvent_names_name_active",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)


class SolventBrand(IsActiveMixin, SoftDeleteModel):
    __tablename__ = "solvent_brands"
    __table_args__ = (
        Index(
            "uq_solvent_brands_name_active",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)


class SolventSheet(AuditUserMixin, SoftDeleteModel):
    __tablename__ = "solvent_sheets"
    __table_args__ = (
        Index(
            "uq_solvent_sheets_company_active",
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


class SolventLine(SoftDeleteModel):
    __tablename__ = "solvent_lines"
    __table_args__ = (
        Index(
            "uq_solvent_lines_sheet_brand_code_active",
            "solvent_sheet_id",
            "brand_id",
            "solvent_name_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_solvent_lines_solvent_name_id", "solvent_name_id"),
        Index("ix_solvent_lines_brand_id", "brand_id"),
    )

    solvent_sheet_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("solvent_sheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    brand_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("solvent_brands.id", ondelete="RESTRICT"),
        nullable=False,
    )
    solvent_name_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("solvent_names.id", ondelete="RESTRICT"),
        nullable=False,
    )
    drum_count: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    drum_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    drum_unit_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("inventory_units.id", ondelete="RESTRICT"),
        nullable=False,
    )
    total_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    solvent_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    total_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)


class SolventMovement(SoftDeleteModel):
    __tablename__ = "solvent_movements"
    __table_args__ = (
        Index("ix_solvent_movements_date", "movement_date"),
        Index("ix_solvent_movements_line", "solvent_line_id"),
    )

    solvent_line_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("solvent_lines.id", ondelete="RESTRICT"),
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
    solvent_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    @property
    def direction_enum(self) -> MaterialMovementDirection:
        return MaterialMovementDirection(self.direction)
