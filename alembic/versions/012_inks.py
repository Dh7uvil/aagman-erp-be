"""Ink colors, brands, sheets, lines, and movements."""

from alembic import op
from sqlalchemy.engine import Connection

from app.db.base import Base

revision = "012_inks"
down_revision = "011_company_gst_number"
branch_labels = None
depends_on = None

_TABLES = (
    "ink_colors",
    "ink_brands",
    "ink_sheets",
    "ink_lines",
    "ink_movements",
)


def upgrade() -> None:
    bind = op.get_bind()
    assert isinstance(bind, Connection)
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[name] for name in _TABLES])


def downgrade() -> None:
    bind = op.get_bind()
    assert isinstance(bind, Connection)
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[name] for name in _TABLES])
