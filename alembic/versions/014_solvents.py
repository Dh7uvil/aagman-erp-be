"""Solvent names, brands, sheets, lines, and movements."""

from alembic import op
from sqlalchemy.engine import Connection

from app.db.base import Base

revision = "014_solvents"
down_revision = "013_adhesives"
branch_labels = None
depends_on = None

_TABLES = (
    "solvent_names",
    "solvent_brands",
    "solvent_sheets",
    "solvent_lines",
    "solvent_movements",
)


def upgrade() -> None:
    bind = op.get_bind()
    assert isinstance(bind, Connection)
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[name] for name in _TABLES])


def downgrade() -> None:
    bind = op.get_bind()
    assert isinstance(bind, Connection)
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[name] for name in _TABLES])
