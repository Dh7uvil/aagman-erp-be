"""Adhesive codes, brands, sheets, lines, and movements."""

from alembic import op
from sqlalchemy.engine import Connection

from app.db.base import Base

revision = "013_adhesives"
down_revision = "012_inks"
branch_labels = None
depends_on = None

_TABLES = (
    "adhesive_codes",
    "adhesive_brands",
    "adhesive_sheets",
    "adhesive_lines",
    "adhesive_movements",
)


def upgrade() -> None:
    bind = op.get_bind()
    assert isinstance(bind, Connection)
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[name] for name in _TABLES])


def downgrade() -> None:
    bind = op.get_bind()
    assert isinstance(bind, Connection)
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[name] for name in _TABLES])
