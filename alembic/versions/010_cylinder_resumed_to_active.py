"""Map legacy RESUMED cylinder status to ACTIVE."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "010_cylinder_resumed_to_active"
down_revision = "009_rename_jobs_to_cylinders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE cylinders SET status = 'ACTIVE' WHERE status = 'RESUMED'"))


def downgrade() -> None:
    pass
