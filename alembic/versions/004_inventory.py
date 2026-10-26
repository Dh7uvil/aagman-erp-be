"""Inventory units, product/micron/SKU hierarchy, and movements."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "004_inventory"
down_revision = "003_company_bill_ship_addresses"
branch_labels = None
depends_on = None


def _inventory_tables_present() -> bool:
    bind = op.get_bind()
    return inspect(bind).has_table("inventory_units")


def upgrade() -> None:
    # 001_initial runs Base.metadata.create_all(), which already creates inventory tables
    # when app.inventory.models is registered. Skip duplicate DDL for that path.
    if _inventory_tables_present():
        return

    op.create_table(
        "inventory_units",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_inventory_units_code_active",
        "inventory_units",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "material_categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "category_kind",
            sa.String(length=20),
            server_default="product",
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("unit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("size", sa.Numeric(18, 4), nullable=True),
        sa.Column("size_unit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rolls_on_hand", sa.Numeric(18, 4), nullable=True),
        sa.Column("total_kg", sa.Numeric(18, 4), nullable=True),
        sa.Column("price_per_unit", sa.Numeric(18, 4), nullable=True),
        sa.Column("price_unit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["parent_id"], ["material_categories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["unit_id"], ["inventory_units.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["size_unit_id"], ["inventory_units.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["price_unit_id"], ["inventory_units.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_material_categories_parent_id", "material_categories", ["parent_id"])
    op.create_index("ix_material_categories_category_kind", "material_categories", ["category_kind"])
    op.create_index(
        "uq_material_categories_product_name_active",
        "material_categories",
        ["name"],
        unique=True,
        postgresql_where=sa.text(
            "category_kind = 'product' AND parent_id IS NULL AND deleted_at IS NULL"
        ),
    )
    op.create_index(
        "uq_material_categories_micron_name_active",
        "material_categories",
        ["parent_id", "name"],
        unique=True,
        postgresql_where=sa.text("category_kind = 'micron' AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_material_categories_sku_size_active",
        "material_categories",
        ["parent_id", "size", "size_unit_id"],
        unique=True,
        postgresql_where=sa.text("category_kind = 'sku' AND deleted_at IS NULL"),
    )

    op.create_table(
        "material_movements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("movement_date", sa.Date(), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("rolls", sa.Numeric(18, 4), nullable=False),
        sa.Column("kilograms", sa.Numeric(18, 4), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["category_id"], ["material_categories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_material_movements_date", "material_movements", ["movement_date"])
    op.create_index("ix_material_movements_category", "material_movements", ["category_id"])


def downgrade() -> None:
    # On current installs, 001_initial already created these tables before 004 runs.
    if _inventory_tables_present():
        return
    op.drop_table("material_movements")
    op.drop_table("material_categories")
    op.drop_table("inventory_units")
