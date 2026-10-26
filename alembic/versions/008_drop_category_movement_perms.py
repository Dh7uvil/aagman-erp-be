"""Drop category and material_movement permissions; grants fold into material."""

import sqlalchemy as sa
from alembic import op

revision = "008_drop_category_movement_perms"
down_revision = "007_identity_perm_module"
branch_labels = None
depends_on = None


def _repoint_grants(*, old_resource: str, action_map: dict[str, str]) -> None:
    for old_action, new_action in action_map.items():
        op.execute(
            sa.text(
                """
                DELETE FROM role_permissions old_rp
                USING permissions old_p, permissions new_p, role_permissions new_rp
                WHERE old_p.module = 'inventory'
                  AND old_p.resource = :old_resource
                  AND old_p.action = :old_action
                  AND new_p.module = 'inventory'
                  AND new_p.resource = 'material'
                  AND new_p.action = :new_action
                  AND old_rp.permission_id = old_p.id
                  AND new_rp.role_id = old_rp.role_id
                  AND new_rp.permission_id = new_p.id
                  AND old_p.id <> new_p.id
                """
            ).bindparams(
                old_resource=old_resource,
                old_action=old_action,
                new_action=new_action,
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE role_permissions rp
                SET permission_id = new_p.id
                FROM permissions old_p
                JOIN permissions new_p
                  ON new_p.module = 'inventory'
                 AND new_p.resource = 'material'
                 AND new_p.action = :new_action
                WHERE old_p.module = 'inventory'
                  AND old_p.resource = :old_resource
                  AND old_p.action = :old_action
                  AND rp.permission_id = old_p.id
                  AND old_p.id <> new_p.id
                """
            ).bindparams(
                old_resource=old_resource,
                old_action=old_action,
                new_action=new_action,
            )
        )


def upgrade() -> None:
    for action in ("create", "read", "update", "delete"):
        _repoint_grants(old_resource="category", action_map={action: action})

    _repoint_grants(
        old_resource="material_movement",
        action_map={
            "read": "read",
            "create": "update",
            "delete": "update",
        },
    )

    op.execute(
        sa.text(
            """
            DELETE FROM role_permissions rp
            USING permissions p
            WHERE rp.permission_id = p.id
              AND p.module = 'inventory'
              AND p.resource IN ('category', 'material_movement')
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM permissions
            WHERE module = 'inventory'
              AND resource IN ('category', 'material_movement')
            """
        )
    )


def downgrade() -> None:
    pass
