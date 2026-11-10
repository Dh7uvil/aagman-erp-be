"""Add optional GST number on companies."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "011_company_gst_number"
down_revision = "010_cylinder_resumed_to_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("companies")}
    if "gst_number" not in columns:
        op.add_column(
            "companies",
            sa.Column("gst_number", sa.String(length=15), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("companies")}
    if "gst_number" in columns:
        op.drop_column("companies", "gst_number")
