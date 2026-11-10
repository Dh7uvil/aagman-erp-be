"""Rename jobs domain to cylinders (tables, permissions, prefs, audit, storage keys)."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "009_rename_jobs_to_cylinders"
down_revision = "008_material_company"
branch_labels = None
depends_on = None


def _rewrite_jsonb_keys(conn: sa.Connection, table: str, column: str) -> None:
    for old_key, new_key in (
        ("job_number", "cylinder_number"),
        ("job_id", "cylinder_id"),
        ("job_image", "cylinder_image"),
    ):
        conn.execute(
            sa.text(
                f"""
                UPDATE {table}
                SET {column} = ({column} - '{old_key}') || jsonb_build_object('{new_key}', {column} -> '{old_key}')
                WHERE {column} ? '{old_key}'
                """
            )
        )


def _rewrite_jsonb_storage_strings(conn: sa.Connection, table: str, column: str) -> None:
    conn.execute(
        sa.text(
            f"""
            UPDATE {table}
            SET {column} = replace(
                replace({column}::text, 'jobs/', 'cylinders/'),
                '/job_image/', '/cylinder_image/'
            )::jsonb
            WHERE {column}::text LIKE '%jobs/%' OR {column}::text LIKE '%job_image%'
            """
        )
    )


def _merge_permission_resource(
    conn: sa.Connection,
    *,
    old_resource: str,
    new_resource: str,
) -> None:
    """Point role grants at new_resource rows; drop legacy job* permission rows if both exist."""
    module = "inventory"
    rows = (
        conn.execute(
            sa.text(
                """
                SELECT old_p.id AS old_id, new_p.id AS new_id
                FROM permissions old_p
                LEFT JOIN permissions new_p
                  ON new_p.module = old_p.module
                 AND new_p.resource = :new_resource
                 AND new_p.action = old_p.action
                WHERE old_p.module = :module
                  AND old_p.resource = :old_resource
                """
            ),
            {"module": module, "old_resource": old_resource, "new_resource": new_resource},
        )
        .mappings()
        .all()
    )

    for row in rows:
        old_id = row["old_id"]
        new_id = row["new_id"]
        if new_id is not None:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO role_permissions (id, created_at, updated_at, role_id, permission_id)
                    SELECT gen_random_uuid(), NOW(), NOW(), rp.role_id, :new_id
                    FROM role_permissions rp
                    WHERE rp.permission_id = :old_id
                      AND NOT EXISTS (
                        SELECT 1
                        FROM role_permissions rp2
                        WHERE rp2.role_id = rp.role_id
                          AND rp2.permission_id = :new_id
                      )
                    """
                ),
                {"old_id": old_id, "new_id": new_id},
            )
            conn.execute(
                sa.text("DELETE FROM role_permissions WHERE permission_id = :old_id"),
                {"old_id": old_id},
            )
            conn.execute(
                sa.text("DELETE FROM permissions WHERE id = :old_id"),
                {"old_id": old_id},
            )
        else:
            conn.execute(
                sa.text(
                    "UPDATE permissions SET resource = :new_resource WHERE id = :old_id"
                ),
                {"new_resource": new_resource, "old_id": old_id},
            )


def _migrate_upload_dirs() -> None:
    from app.core.config import get_settings

    upload_root = Path(get_settings().upload_dir)
    jobs_root = upload_root / "jobs"
    if not jobs_root.is_dir():
        return
    cylinders_root = upload_root / "cylinders"
    if cylinders_root.exists():
        return
    jobs_root.rename(cylinders_root)
    for record_dir in cylinders_root.iterdir():
        if not record_dir.is_dir():
            continue
        image_slot = record_dir / "job_image"
        if image_slot.is_dir():
            image_slot.rename(record_dir / "cylinder_image")


def upgrade() -> None:
    conn = op.get_bind()

    op.rename_table("jobs", "cylinders")
    op.alter_column("cylinders", "job_number", new_column_name="cylinder_number")
    op.alter_column("cylinders", "job_image_storage_key", new_column_name="cylinder_image_storage_key")
    op.alter_column("cylinders", "job_image_filename", new_column_name="cylinder_image_filename")
    op.alter_column("cylinders", "job_image_content_type", new_column_name="cylinder_image_content_type")
    op.alter_column("cylinders", "job_image_size_bytes", new_column_name="cylinder_image_size_bytes")

    conn.execute(
        sa.text(
            """
            UPDATE cylinders
            SET cylinder_image_storage_key = replace(
                replace(cylinder_image_storage_key, 'jobs/', 'cylinders/'),
                '/job_image/', '/cylinder_image/'
            )
            WHERE cylinder_image_storage_key IS NOT NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE cylinders
            SET challan_storage_key = replace(challan_storage_key, 'jobs/', 'cylinders/')
            WHERE challan_storage_key IS NOT NULL
            """
        )
    )

    op.rename_table("job_cylinders", "cylinder_sizes")
    op.alter_column("cylinder_sizes", "job_id", new_column_name="cylinder_id")

    op.rename_table("job_colors", "cylinder_colors")
    op.alter_column("cylinder_colors", "job_id", new_column_name="cylinder_id")

    op.rename_table("job_pauses", "cylinder_pauses")
    op.alter_column("cylinder_pauses", "job_id", new_column_name="cylinder_id")

    op.alter_column("cylinder_returns", "job_id", new_column_name="cylinder_id")

    conn.execute(sa.text("ALTER INDEX IF EXISTS uq_jobs_job_number_active RENAME TO uq_cylinders_cylinder_number_active"))
    conn.execute(sa.text("ALTER INDEX IF EXISTS ix_jobs_company_id RENAME TO ix_cylinders_company_id"))
    conn.execute(sa.text("ALTER INDEX IF EXISTS ix_jobs_status RENAME TO ix_cylinders_status"))
    conn.execute(
        sa.text(
            "ALTER INDEX IF EXISTS uq_job_cylinders_job_position RENAME TO uq_cylinder_sizes_cylinder_position"
        )
    )
    conn.execute(
        sa.text("ALTER INDEX IF EXISTS uq_job_colors_job_position RENAME TO uq_cylinder_colors_cylinder_position")
    )
    conn.execute(sa.text("ALTER INDEX IF EXISTS uq_job_pauses_open RENAME TO uq_cylinder_pauses_open"))
    conn.execute(
        sa.text(
            "ALTER INDEX IF EXISTS uq_cylinder_returns_job_active RENAME TO uq_cylinder_returns_cylinder_active"
        )
    )

    _merge_permission_resource(conn, old_resource="job", new_resource="cylinder")
    _merge_permission_resource(conn, old_resource="job_image", new_resource="cylinder_image")
    _merge_permission_resource(conn, old_resource="job_challan", new_resource="cylinder_challan")

    conn.execute(
        sa.text(
            "UPDATE user_table_preferences SET table_key = 'inventory.cylinders' "
            "WHERE table_key = 'inventory.jobs'"
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE user_table_preferences
            SET visible_columns = replace(visible_columns::text, 'job_number', 'cylinder_number')::jsonb,
                column_order = replace(column_order::text, 'job_number', 'cylinder_number')::jsonb
            WHERE table_key = 'inventory.cylinders'
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE user_table_preferences
            SET visible_columns = replace(visible_columns::text, '"job"', '"cylinder"')::jsonb,
                column_order = replace(column_order::text, '"job"', '"cylinder"')::jsonb
            WHERE table_key = 'inventory.cylinder_returns'
            """
        )
    )

    conn.execute(sa.text("UPDATE audit_logs SET entity_type = 'cylinder' WHERE entity_type = 'job'"))
    _rewrite_jsonb_keys(conn, "audit_logs", "old_values")
    _rewrite_jsonb_keys(conn, "audit_logs", "new_values")
    _rewrite_jsonb_storage_strings(conn, "audit_logs", "old_values")
    _rewrite_jsonb_storage_strings(conn, "audit_logs", "new_values")

    _migrate_upload_dirs()


def downgrade() -> None:
    raise NotImplementedError("downgrade not supported for jobs → cylinders rename")
