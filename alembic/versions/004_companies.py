"""Companies, including bill-to and ship-to addresses."""

from alembic import op
from sqlalchemy.engine import Connection

from app.db.base import Base

revision = "004_companies"
down_revision = "003_audit"
branch_labels = None
depends_on = None

_TABLES = ("companies",)


def upgrade() -> None:
    bind = op.get_bind()
    assert isinstance(bind, Connection)
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[name] for name in _TABLES])


def downgrade() -> None:
    bind = op.get_bind()
    assert isinstance(bind, Connection)
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[name] for name in _TABLES])
