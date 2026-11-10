"""Identity: addresses, users, roles, tokens, and table preferences."""

from alembic import op
from sqlalchemy.engine import Connection
from sqlalchemy.schema import CreateTable

from app.db.base import Base

revision = "001_identity"
down_revision = None
branch_labels = None
depends_on = None

# users.branch_id and users.department_id point at organization tables, and
# departments.manager_id points back at users. Those two foreign keys are
# added in 002_organization after branches and departments exist.
_BEFORE_USERS = (
    "addresses",
    "roles",
    "permissions",
)
_AFTER_USERS = (
    "user_roles",
    "role_permissions",
    "refresh_tokens",
    "password_reset_tokens",
    "user_table_preferences",
)


def upgrade() -> None:
    bind = op.get_bind()
    assert isinstance(bind, Connection)
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in _BEFORE_USERS],
    )
    op.execute(CreateTable(Base.metadata.tables["users"], include_foreign_key_constraints=[]))
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in _AFTER_USERS],
    )


def downgrade() -> None:
    bind = op.get_bind()
    assert isinstance(bind, Connection)
    Base.metadata.drop_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in ("users", *_BEFORE_USERS, *_AFTER_USERS)],
    )
