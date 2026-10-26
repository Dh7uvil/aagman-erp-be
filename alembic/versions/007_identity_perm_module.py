"""Restore permission module name identity (from organization)."""

import sqlalchemy as sa
from alembic import op

revision = "007_identity_perm_module"
down_revision = "006_org_perm_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM role_permissions old_rp
            USING permissions old_p, permissions new_p, role_permissions new_rp
            WHERE old_p.module = 'organization'
              AND new_p.module = 'identity'
              AND old_p.resource = new_p.resource
              AND old_p.action = new_p.action
              AND old_rp.permission_id = old_p.id
              AND new_rp.role_id = old_rp.role_id
              AND new_rp.permission_id = new_p.id
              AND old_p.id <> new_p.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE role_permissions rp
            SET permission_id = new_p.id
            FROM permissions old_p
            JOIN permissions new_p
              ON new_p.module = 'identity'
             AND new_p.resource = old_p.resource
             AND new_p.action = old_p.action
            WHERE old_p.module = 'organization'
              AND rp.permission_id = old_p.id
              AND old_p.id <> new_p.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM permissions old_p
            USING permissions new_p
            WHERE old_p.module = 'organization'
              AND new_p.module = 'identity'
              AND old_p.resource = new_p.resource
              AND old_p.action = new_p.action
              AND old_p.id <> new_p.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE permissions
            SET module = 'identity'
            WHERE module = 'organization'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE user_table_preferences
            SET table_key = 'identity.' || substring(table_key from 14)
            WHERE table_key LIKE 'organization.%'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE audit_logs
            SET module = 'identity'
            WHERE module = 'organization'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE audit_logs
            SET module = 'organization'
            WHERE module = 'identity'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE user_table_preferences
            SET table_key = 'organization.' || substring(table_key from 10)
            WHERE table_key LIKE 'identity.%'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE permissions
            SET module = 'organization'
            WHERE module = 'identity'
            """
        )
    )
