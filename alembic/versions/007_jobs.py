"""Jobs, pauses, and cylinder returns."""

from alembic import op
from sqlalchemy.engine import Connection

from app.db.base import Base

revision = "007_jobs"
down_revision = "006_materials"
branch_labels = None
depends_on = None

_TABLES = (
    "jobs",
    "job_cylinders",
    "job_colors",
    "job_pauses",
    "cylinder_returns",
)


def upgrade() -> None:
    bind = op.get_bind()
    assert isinstance(bind, Connection)
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[name] for name in _TABLES])


def downgrade() -> None:
    bind = op.get_bind()
    assert isinstance(bind, Connection)
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[name] for name in _TABLES])
