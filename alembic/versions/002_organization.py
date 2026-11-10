"""Organization profile, branches, departments, and warehouses."""

from alembic import op
from sqlalchemy.engine import Connection

from app.db.base import Base

revision = "002_organization"
down_revision = "001_identity"
branch_labels = None
depends_on = None

_TABLES = (
    "branches",
    "departments",
    "organizations",
    "warehouses",
)


def upgrade() -> None:
    bind = op.get_bind()
    assert isinstance(bind, Connection)
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[name] for name in _TABLES])
    op.create_foreign_key(
        "users_branch_id_fkey",
        "users",
        "branches",
        ["branch_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "users_department_id_fkey",
        "users",
        "departments",
        ["department_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("users_department_id_fkey", "users", type_="foreignkey")
    op.drop_constraint("users_branch_id_fkey", "users", type_="foreignkey")
    bind = op.get_bind()
    assert isinstance(bind, Connection)
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[name] for name in _TABLES])
