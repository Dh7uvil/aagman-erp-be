"""Reorganize inventory permission catalog keys."""

import sqlalchemy as sa
from alembic import op

revision = "005_permission_catalog_reorg"
down_revision = "004_inventory"
branch_labels = None
depends_on = None


def _merge_resource(
    *,
    old_resource: str,
    new_resource: str,
    actions: tuple[str, ...],
) -> None:
    for action in actions:
        op.execute(
            sa.text(
                """
                DELETE FROM role_permissions old_rp
                USING permissions old_perm, permissions new_perm, role_permissions new_rp
                WHERE old_perm.module = 'inventory'
                  AND old_perm.resource = :old_resource
                  AND old_perm.action = :action
                  AND new_perm.module = 'inventory'
                  AND new_perm.resource = :new_resource
                  AND new_perm.action = :action
                  AND old_rp.permission_id = old_perm.id
                  AND new_rp.role_id = old_rp.role_id
                  AND new_rp.permission_id = new_perm.id
                  AND old_perm.id <> new_perm.id
                """
            ).bindparams(
                old_resource=old_resource,
                new_resource=new_resource,
                action=action,
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE role_permissions rp
                SET permission_id = new_perm.id
                FROM permissions old_perm
                JOIN permissions new_perm
                  ON new_perm.module = 'inventory'
                 AND new_perm.resource = :new_resource
                 AND new_perm.action = :action
                WHERE old_perm.module = 'inventory'
                  AND old_perm.resource = :old_resource
                  AND old_perm.action = :action
                  AND rp.permission_id = old_perm.id
                  AND old_perm.id <> new_perm.id
                """
            ).bindparams(
                old_resource=old_resource,
                new_resource=new_resource,
                action=action,
            )
        )
    op.execute(
        sa.text(
            """
            DELETE FROM permissions old_perm
            USING permissions new_perm
            WHERE old_perm.module = 'inventory'
              AND old_perm.resource = :old_resource
              AND new_perm.module = 'inventory'
              AND new_perm.resource = :new_resource
              AND new_perm.action = old_perm.action
              AND old_perm.id <> new_perm.id
            """
        ).bindparams(old_resource=old_resource, new_resource=new_resource)
    )
    op.execute(
        sa.text(
            """
            UPDATE permissions
            SET resource = :new_resource
            WHERE module = 'inventory' AND resource = :old_resource
            """
        ).bindparams(old_resource=old_resource, new_resource=new_resource)
    )


def upgrade() -> None:
    _merge_resource(
        old_resource="movement",
        new_resource="material_movement",
        actions=("create", "read", "delete"),
    )

    op.execute(
        sa.text(
            """
            DELETE FROM role_permissions old_rp
            USING permissions old_perm, permissions new_perm, role_permissions new_rp
            WHERE old_perm.module = 'inventory'
              AND old_perm.resource = 'price'
              AND old_perm.action = 'read'
              AND new_perm.module = 'inventory'
              AND new_perm.resource = 'material'
              AND new_perm.action = 'view_price'
              AND old_rp.permission_id = old_perm.id
              AND new_rp.role_id = old_rp.role_id
              AND new_rp.permission_id = new_perm.id
              AND old_perm.id <> new_perm.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE role_permissions rp
            SET permission_id = new_perm.id
            FROM permissions old_perm
            JOIN permissions new_perm
              ON new_perm.module = 'inventory'
             AND new_perm.resource = 'material'
             AND new_perm.action = 'view_price'
            WHERE old_perm.module = 'inventory'
              AND old_perm.resource = 'price'
              AND old_perm.action = 'read'
              AND rp.permission_id = old_perm.id
              AND old_perm.id <> new_perm.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM permissions old_perm
            USING permissions new_perm
            WHERE old_perm.module = 'inventory'
              AND old_perm.resource = 'price'
              AND old_perm.action = 'read'
              AND new_perm.module = 'inventory'
              AND new_perm.resource = 'material'
              AND new_perm.action = 'view_price'
              AND old_perm.id <> new_perm.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE permissions
            SET resource = 'material', action = 'view_price'
            WHERE module = 'inventory' AND resource = 'price' AND action = 'read'
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO permissions (id, module, resource, action, created_at, updated_at)
            SELECT gen_random_uuid(), 'inventory', 'materials_report', 'read', now(), now()
            WHERE NOT EXISTS (
                SELECT 1 FROM permissions
                WHERE module = 'inventory'
                  AND resource = 'materials_report'
                  AND action = 'read'
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO role_permissions (id, role_id, permission_id, created_at, updated_at)
            SELECT gen_random_uuid(), rp.role_id, report_perm.id, now(), now()
            FROM role_permissions rp
            JOIN permissions movement_perm ON movement_perm.id = rp.permission_id
            JOIN permissions report_perm
              ON report_perm.module = 'inventory'
             AND report_perm.resource = 'materials_report'
             AND report_perm.action = 'read'
            WHERE movement_perm.module = 'inventory'
              AND movement_perm.resource = 'material_movement'
              AND movement_perm.action = 'read'
              AND NOT EXISTS (
                SELECT 1 FROM role_permissions existing
                WHERE existing.role_id = rp.role_id
                  AND existing.permission_id = report_perm.id
              )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM role_permissions rp
            USING permissions p
            WHERE rp.permission_id = p.id
              AND p.module = 'inventory'
              AND p.resource = 'materials_report'
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM permissions
            WHERE module = 'inventory' AND resource = 'materials_report'
            """
        )
    )

    _merge_resource(
        old_resource="material",
        new_resource="price",
        actions=("view_price",),
    )
    op.execute(
        sa.text(
            """
            UPDATE permissions
            SET resource = 'price', action = 'read'
            WHERE module = 'inventory'
              AND resource = 'material'
              AND action = 'view_price'
            """
        )
    )

    _merge_resource(
        old_resource="material_movement",
        new_resource="movement",
        actions=("create", "read", "delete"),
    )
