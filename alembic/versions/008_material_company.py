"""Material product company link and movement price/company snapshots."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "008_material_company"
down_revision = "007_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "material_categories",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_material_categories_company_id",
        "material_categories",
        ["company_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_material_categories_company_id_companies",
        "material_categories",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_index(
        "uq_material_categories_product_name_active",
        table_name="material_categories",
        postgresql_where=sa.text(
            "category_kind = 'product' AND parent_id IS NULL AND deleted_at IS NULL"
        ),
    )
    op.create_index(
        "uq_material_categories_product_company_name_active",
        "material_categories",
        ["company_id", "name"],
        unique=True,
        postgresql_where=sa.text(
            "category_kind = 'product' AND parent_id IS NULL AND company_id IS NOT NULL AND deleted_at IS NULL"
        ),
    )
    op.create_index(
        "uq_material_categories_product_name_nocompany_active",
        "material_categories",
        ["name"],
        unique=True,
        postgresql_where=sa.text(
            "category_kind = 'product' AND parent_id IS NULL AND company_id IS NULL AND deleted_at IS NULL"
        ),
    )

    op.add_column(
        "material_movements",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "material_movements",
        sa.Column("price_per_unit", sa.Numeric(18, 4), nullable=True),
    )
    op.add_column(
        "material_movements",
        sa.Column("price_unit_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_material_movements_company_id",
        "material_movements",
        ["company_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_material_movements_company_id_companies",
        "material_movements",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_material_movements_price_unit_id_inventory_units",
        "material_movements",
        "inventory_units",
        ["price_unit_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_material_movements_price_unit_id_inventory_units",
        "material_movements",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_material_movements_company_id_companies",
        "material_movements",
        type_="foreignkey",
    )
    op.drop_index("ix_material_movements_company_id", table_name="material_movements")
    op.drop_column("material_movements", "price_unit_id")
    op.drop_column("material_movements", "price_per_unit")
    op.drop_column("material_movements", "company_id")

    op.drop_constraint(
        "fk_material_categories_company_id_companies",
        "material_categories",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_material_categories_product_name_nocompany_active",
        table_name="material_categories",
        postgresql_where=sa.text(
            "category_kind = 'product' AND parent_id IS NULL AND company_id IS NULL AND deleted_at IS NULL"
        ),
    )
    op.drop_index(
        "uq_material_categories_product_company_name_active",
        table_name="material_categories",
        postgresql_where=sa.text(
            "category_kind = 'product' AND parent_id IS NULL AND company_id IS NOT NULL AND deleted_at IS NULL"
        ),
    )
    op.create_index(
        "uq_material_categories_product_name_active",
        "material_categories",
        ["name"],
        unique=True,
        postgresql_where=sa.text(
            "category_kind = 'product' AND parent_id IS NULL AND deleted_at IS NULL"
        ),
    )
    op.drop_index("ix_material_categories_company_id", table_name="material_categories")
    op.drop_column("material_categories", "company_id")
