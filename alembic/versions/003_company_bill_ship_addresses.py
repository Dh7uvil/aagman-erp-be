"""Add bill-to and ship-to address columns on companies."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "003_company_bill_ship_addresses"
down_revision = "002_companies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("companies")}
    if "bill_to_address_id" not in columns:
        op.add_column(
            "companies",
            sa.Column("bill_to_address_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_companies_bill_to_address_id_addresses",
            "companies",
            "addresses",
            ["bill_to_address_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if "ship_to_address_id" not in columns:
        op.add_column(
            "companies",
            sa.Column("ship_to_address_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_companies_ship_to_address_id_addresses",
            "companies",
            "addresses",
            ["ship_to_address_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("companies")}
    if "ship_to_address_id" in columns:
        op.drop_constraint(
            "fk_companies_ship_to_address_id_addresses",
            "companies",
            type_="foreignkey",
        )
        op.drop_column("companies", "ship_to_address_id")
    if "bill_to_address_id" in columns:
        op.drop_constraint(
            "fk_companies_bill_to_address_id_addresses",
            "companies",
            type_="foreignkey",
        )
        op.drop_column("companies", "bill_to_address_id")
