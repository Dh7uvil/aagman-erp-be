"""Permission catalog and seed helpers."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import IDENTITY_MODULE, SYSTEM_ADMIN_ROLE_NAME
from app.core.permissions import build_permission
from app.identity.models import Permission, Role, RolePermission

USER_CREATE = build_permission(IDENTITY_MODULE, "user", "create")
USER_READ = build_permission(IDENTITY_MODULE, "user", "read")
USER_UPDATE = build_permission(IDENTITY_MODULE, "user", "update")
USER_DELETE = build_permission(IDENTITY_MODULE, "user", "delete")
ROLE_CREATE = build_permission(IDENTITY_MODULE, "role", "create")
ROLE_READ = build_permission(IDENTITY_MODULE, "role", "read")
ROLE_UPDATE = build_permission(IDENTITY_MODULE, "role", "update")
ROLE_DELETE = build_permission(IDENTITY_MODULE, "role", "delete")
PERMISSION_READ = build_permission(IDENTITY_MODULE, "permission", "read")
ORGANIZATION_READ = build_permission(IDENTITY_MODULE, "organization", "read")
ORGANIZATION_UPDATE = build_permission(IDENTITY_MODULE, "organization", "update")
BRANCH_CREATE = build_permission(IDENTITY_MODULE, "branch", "create")
BRANCH_READ = build_permission(IDENTITY_MODULE, "branch", "read")
BRANCH_UPDATE = build_permission(IDENTITY_MODULE, "branch", "update")
BRANCH_DELETE = build_permission(IDENTITY_MODULE, "branch", "delete")
DEPARTMENT_CREATE = build_permission(IDENTITY_MODULE, "department", "create")
DEPARTMENT_READ = build_permission(IDENTITY_MODULE, "department", "read")
DEPARTMENT_UPDATE = build_permission(IDENTITY_MODULE, "department", "update")
DEPARTMENT_DELETE = build_permission(IDENTITY_MODULE, "department", "delete")
WAREHOUSE_CREATE = build_permission(IDENTITY_MODULE, "warehouse", "create")
WAREHOUSE_READ = build_permission(IDENTITY_MODULE, "warehouse", "read")
WAREHOUSE_UPDATE = build_permission(IDENTITY_MODULE, "warehouse", "update")
WAREHOUSE_DELETE = build_permission(IDENTITY_MODULE, "warehouse", "delete")
AUDIT_LOG_READ = build_permission(IDENTITY_MODULE, "audit_log", "read")

_CATALOG: dict[str, tuple[str, ...]] = {
    "user": ("create", "read", "update", "delete"),
    "role": ("create", "read", "update", "delete"),
    "permission": ("read",),
    "organization": ("read", "update"),
    "branch": ("create", "read", "update", "delete"),
    "department": ("create", "read", "update", "delete"),
    "warehouse": ("create", "read", "update", "delete"),
    "audit_log": ("read",),
}


def catalog_permission_strings() -> list[str]:
    return [
        build_permission(IDENTITY_MODULE, resource, action)
        for resource, actions in _CATALOG.items()
        for action in actions
    ]


async def seed_permissions(session: AsyncSession) -> None:
    existing = {
        (row.module, row.resource, row.action)
        for row in (await session.execute(select(Permission))).scalars().all()
    }
    for resource, actions in _CATALOG.items():
        for action in actions:
            key = (IDENTITY_MODULE, resource, action)
            if key in existing:
                continue
            session.add(
                Permission(module=IDENTITY_MODULE, resource=resource, action=action),
            )
    await session.flush()


async def grant_all_permissions_to_role(session: AsyncSession, role_id) -> None:
    await seed_permissions(session)
    permissions = (await session.execute(select(Permission))).scalars().all()
    existing = {
        row.permission_id
        for row in (
            await session.execute(
                select(RolePermission.permission_id).where(RolePermission.role_id == role_id),
            )
        ).all()
    }
    for perm in permissions:
        if perm.id in existing:
            continue
        session.add(RolePermission(role_id=role_id, permission_id=perm.id))
    await session.flush()


async def ensure_superadmin_catalog(session: AsyncSession, role: Role) -> None:
    if role.name != SYSTEM_ADMIN_ROLE_NAME:
        return
    await grant_all_permissions_to_role(session, role.id)


async def get_system_admin_role(session: AsyncSession) -> Role | None:
    result = await session.execute(
        select(Role).where(
            Role.is_system_role.is_(True),
            Role.name == SYSTEM_ADMIN_ROLE_NAME,
        )
    )
    return result.scalar_one_or_none()


async def ensure_superadmin(session: AsyncSession) -> None:
    """Seed the permission catalog and grant any new permissions to Superadmin."""

    await seed_permissions(session)
    role = await get_system_admin_role(session)
    if role is not None:
        await ensure_superadmin_catalog(session, role)


async def grant_catalog_to_role(session: AsyncSession, role_id: UUID) -> None:
    await grant_all_permissions_to_role(session, role_id)
