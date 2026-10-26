"""Inventory ORM models."""

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

from app.core.enums import MaterialCategoryKind, MaterialMovementDirection
from app.db.base import SoftDeleteModel
from app.db.mixins import IsActiveMixin


class InventoryUnit(IsActiveMixin, SoftDeleteModel):
    __tablename__ = "inventory_units"
    __table_args__ = (
        Index(
            "uq_inventory_units_code_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class MaterialCategory(IsActiveMixin, SoftDeleteModel):
    """Product → micron → SKU hierarchy stored in one table."""

    __tablename__ = "material_categories"
    __table_args__ = (
        Index(
            "uq_material_categories_product_name_active",
            "name",
            unique=True,
            postgresql_where=text(
                "category_kind = 'product' AND parent_id IS NULL AND deleted_at IS NULL"
            ),
        ),
        Index(
            "uq_material_categories_micron_name_active",
            "parent_id",
            "name",
            unique=True,
            postgresql_where=text("category_kind = 'micron' AND deleted_at IS NULL"),
        ),
        Index(
            "uq_material_categories_sku_size_active",
            "parent_id",
            "size",
            "size_unit_id",
            unique=True,
            postgresql_where=text("category_kind = 'sku' AND deleted_at IS NULL"),
        ),
    )

    parent_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("material_categories.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    category_kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    unit_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("inventory_units.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    size: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    size_unit_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("inventory_units.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    rolls_on_hand: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    total_kg: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    price_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    price_unit_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("inventory_units.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    @property
    def kind_enum(self) -> MaterialCategoryKind:
        return MaterialCategoryKind(self.category_kind)


class MaterialMovement(SoftDeleteModel):
    __tablename__ = "material_movements"
    __table_args__ = (
        Index("ix_material_movements_date", "movement_date"),
        Index("ix_material_movements_category", "category_id"),
    )

    category_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("material_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    movement_date: Mapped[date] = mapped_column(Date, nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    rolls: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    kilograms: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    @property
    def direction_enum(self) -> MaterialMovementDirection:
        return MaterialMovementDirection(self.direction)
