"""Add export column preferences to user_table_preferences."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "015_table_export_preferences"
down_revision = "014_solvents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_table_preferences",
        sa.Column("export_visible_columns", JSONB, nullable=True),
    )
    op.add_column(
        "user_table_preferences",
        sa.Column("export_column_order", JSONB, nullable=True),
    )
    op.add_column(
        "user_table_preferences",
        sa.Column("export_format", sa.String(length=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_table_preferences", "export_format")
    op.drop_column("user_table_preferences", "export_column_order")
    op.drop_column("user_table_preferences", "export_visible_columns")
