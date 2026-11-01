"""Material product company link and movement price/company snapshots."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "008_material_company"
down_revision = "007_jobs"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {col["name"] for col in inspector.get_columns(table)}


def _index_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {idx["name"] for idx in inspector.get_indexes(table)}


def _has_foreign_key(
    inspector: sa.Inspector,
    table: str,
    *,
    column: str,
    referred_table: str,
) -> bool:
    for fk in inspector.get_foreign_keys(table):
        if column in fk.get("constrained_columns", []) and fk.get("referred_table") == referred_table:
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    mc_columns = _column_names(inspector, "material_categories")
    mc_indexes = _index_names(inspector, "material_categories")

    if "company_id" not in mc_columns:
        op.add_column(
            "material_categories",
            sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        mc_columns.add("company_id")

    if "ix_material_categories_company_id" not in mc_indexes:
        op.create_index(
            "ix_material_categories_company_id",
            "material_categories",
            ["company_id"],
            unique=False,
        )
        mc_indexes.add("ix_material_categories_company_id")

    if not _has_foreign_key(inspector, "material_categories", column="company_id", referred_table="companies"):
        op.create_foreign_key(
            "fk_material_categories_company_id_companies",
            "material_categories",
            "companies",
            ["company_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    if "uq_material_categories_product_name_active" in mc_indexes:
        op.drop_index(
            "uq_material_categories_product_name_active",
            table_name="material_categories",
            postgresql_where=sa.text(
                "category_kind = 'product' AND parent_id IS NULL AND deleted_at IS NULL"
            ),
        )
        mc_indexes.discard("uq_material_categories_product_name_active")

    if "uq_material_categories_product_company_name_active" not in mc_indexes:
        op.create_index(
            "uq_material_categories_product_company_name_active",
            "material_categories",
            ["company_id", "name"],
            unique=True,
            postgresql_where=sa.text(
                "category_kind = 'product' AND parent_id IS NULL AND company_id IS NOT NULL AND deleted_at IS NULL"
            ),
        )

    if "uq_material_categories_product_name_nocompany_active" not in mc_indexes:
        op.create_index(
            "uq_material_categories_product_name_nocompany_active",
            "material_categories",
            ["name"],
            unique=True,
            postgresql_where=sa.text(
                "category_kind = 'product' AND parent_id IS NULL AND company_id IS NULL AND deleted_at IS NULL"
            ),
        )

    mm_columns = _column_names(inspector, "material_movements")
    mm_indexes = _index_names(inspector, "material_movements")

    if "company_id" not in mm_columns:
        op.add_column(
            "material_movements",
            sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if "price_per_unit" not in mm_columns:
        op.add_column(
            "material_movements",
            sa.Column("price_per_unit", sa.Numeric(18, 4), nullable=True),
        )
    if "price_unit_id" not in mm_columns:
        op.add_column(
            "material_movements",
            sa.Column("price_unit_id", postgresql.UUID(as_uuid=True), nullable=True),
        )

    if "ix_material_movements_company_id" not in mm_indexes:
        op.create_index(
            "ix_material_movements_company_id",
            "material_movements",
            ["company_id"],
            unique=False,
        )

    if not _has_foreign_key(inspector, "material_movements", column="company_id", referred_table="companies"):
        op.create_foreign_key(
            "fk_material_movements_company_id_companies",
            "material_movements",
            "companies",
            ["company_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if not _has_foreign_key(inspector, "material_movements", column="price_unit_id", referred_table="inventory_units"):
        op.create_foreign_key(
            "fk_material_movements_price_unit_id_inventory_units",
            "material_movements",
            "inventory_units",
            ["price_unit_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    mm_columns = _column_names(inspector, "material_movements")
    if "price_unit_id" in mm_columns and _has_foreign_key(
        inspector, "material_movements", column="price_unit_id", referred_table="inventory_units"
    ):
        op.drop_constraint(
            "fk_material_movements_price_unit_id_inventory_units",
            "material_movements",
            type_="foreignkey",
        )
    if "company_id" in mm_columns and _has_foreign_key(
        inspector, "material_movements", column="company_id", referred_table="companies"
    ):
        op.drop_constraint(
            "fk_material_movements_company_id_companies",
            "material_movements",
            type_="foreignkey",
        )
    if "ix_material_movements_company_id" in _index_names(inspector, "material_movements"):
        op.drop_index("ix_material_movements_company_id", table_name="material_movements")
    if "price_unit_id" in mm_columns:
        op.drop_column("material_movements", "price_unit_id")
    if "price_per_unit" in mm_columns:
        op.drop_column("material_movements", "price_per_unit")
    if "company_id" in mm_columns:
        op.drop_column("material_movements", "company_id")

    mc_indexes = _index_names(inspector, "material_categories")
    if _has_foreign_key(inspector, "material_categories", column="company_id", referred_table="companies"):
        op.drop_constraint(
            "fk_material_categories_company_id_companies",
            "material_categories",
            type_="foreignkey",
        )
    if "uq_material_categories_product_name_nocompany_active" in mc_indexes:
        op.drop_index(
            "uq_material_categories_product_name_nocompany_active",
            table_name="material_categories",
            postgresql_where=sa.text(
                "category_kind = 'product' AND parent_id IS NULL AND company_id IS NULL AND deleted_at IS NULL"
            ),
        )
    if "uq_material_categories_product_company_name_active" in mc_indexes:
        op.drop_index(
            "uq_material_categories_product_company_name_active",
            table_name="material_categories",
            postgresql_where=sa.text(
                "category_kind = 'product' AND parent_id IS NULL AND company_id IS NOT NULL AND deleted_at IS NULL"
            ),
        )
    if "uq_material_categories_product_name_active" not in mc_indexes:
        op.create_index(
            "uq_material_categories_product_name_active",
            "material_categories",
            ["name"],
            unique=True,
            postgresql_where=sa.text(
                "category_kind = 'product' AND parent_id IS NULL AND deleted_at IS NULL"
            ),
        )
    if "ix_material_categories_company_id" in mc_indexes:
        op.drop_index("ix_material_categories_company_id", table_name="material_categories")
    if "company_id" in _column_names(inspector, "material_categories"):
        op.drop_column("material_categories", "company_id")
