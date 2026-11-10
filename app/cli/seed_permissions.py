"""Seed the permission catalog and grant every permission to Superadmin."""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import func, select

from app.core.exceptions import ValidationError
from app.db.session import async_session_factory, transaction
from app.identity.catalog import ensure_superadmin, get_system_admin_role
from app.identity.models import Permission, RolePermission


async def seed_and_grant_superadmin() -> tuple[int, int]:
    async with async_session_factory() as session, transaction(session):
        role = await get_system_admin_role(session)
        if role is None:
            raise ValidationError(
                "Superadmin role does not exist. Run `uv run bootstrap` first.",
            )

        await ensure_superadmin(session)
        permission_count = await session.scalar(select(func.count()).select_from(Permission))
        granted_count = await session.scalar(
            select(func.count())
            .select_from(RolePermission)
            .where(RolePermission.role_id == role.id)
        )
        return int(permission_count or 0), int(granted_count or 0)


def main() -> None:
    try:
        permission_count, granted_count = asyncio.run(seed_and_grant_superadmin())
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    print("Permissions seeded and granted to Superadmin")
    print(f"  permissions: {permission_count}")
    print(f"  granted:     {granted_count}")


if __name__ == "__main__":
    main()
