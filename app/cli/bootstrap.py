"""Interactive CLI to provision the singleton organization and admin user."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from getpass import getpass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.common.utils.validators import normalize_required_text
from app.core.enums import SYSTEM_ADMIN_ROLE_NAME, UserStatus
from app.core.exceptions import DuplicateResourceError, ValidationError
from app.core.security import PasswordTooLongError, hash_password
from app.db.session import async_session_factory, transaction
from app.identity.catalog import grant_all_permissions_to_role, seed_permissions
from app.identity.models import Organization, Role, User, UserRole


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    organization_id: UUID
    organization_name: str
    admin_email: str
    admin_role: str


def _normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or "@" not in normalized:
        raise ValidationError("Admin email must be a valid email address")
    if len(normalized) > 255:
        raise ValidationError("Admin email must be at most 255 characters")
    return normalized


def _prompt_inputs() -> tuple[str, str, str, str]:
    org_name = normalize_required_text(input("Organization name: "), field_name="Organization name")
    admin_name = normalize_required_text(input("Admin name: "), field_name="Admin name")
    admin_email = _normalize_email(input("Admin email: "))
    password = getpass("Password: ")
    confirm = getpass("Confirm password: ")
    if not password:
        raise ValidationError("Password must not be empty")
    if password != confirm:
        raise ValidationError("Passwords do not match")
    return org_name, admin_name, admin_email, password


async def provision_organization(
    *,
    organization_name: str,
    admin_name: str,
    admin_email: str,
    password_hash: str,
    timezone: str = "Asia/Dubai",
) -> BootstrapResult:
    async with async_session_factory() as session, transaction(session):
        existing = await session.execute(select(Organization).limit(1))
        if existing.scalar_one_or_none() is not None:
            raise DuplicateResourceError("Organization already exists; bootstrap is one-time")

        org = Organization(name=organization_name, timezone=timezone, settings={})
        session.add(org)
        await session.flush()

        await seed_permissions(session)
        role = Role(
            name=SYSTEM_ADMIN_ROLE_NAME,
            description="Superadmin with all catalog permissions",
            is_system_role=True,
        )
        session.add(role)
        await session.flush()
        await grant_all_permissions_to_role(session, role.id)

        user = User(
            name=admin_name,
            email=admin_email,
            password_hash=password_hash,
            status=UserStatus.ACTIVE,
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError as exc:
            raise DuplicateResourceError("A user with this email already exists") from exc

        session.add(UserRole(user_id=user.id, role_id=role.id))
        await session.flush()

        return BootstrapResult(
            organization_id=org.id,
            organization_name=org.name,
            admin_email=user.email,
            admin_role=role.name,
        )


def _print_summary(result: BootstrapResult) -> None:
    print("Organization provisioned successfully")
    print(f"  organization_id: {result.organization_id}")
    print(f"  name:            {result.organization_name}")
    print(f"  admin_email:     {result.admin_email}")
    print(f"  admin_role:      {result.admin_role}")


def main() -> None:
    try:
        org_name, admin_name, admin_email, password = _prompt_inputs()
        password_hash = hash_password(password)
        result = asyncio.run(
            provision_organization(
                organization_name=org_name,
                admin_name=admin_name,
                admin_email=admin_email,
                password_hash=password_hash,
            )
        )
    except (PasswordTooLongError, ValidationError, DuplicateResourceError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        print("\nCancelled", file=sys.stderr)
        raise SystemExit(1) from None

    _print_summary(result)


if __name__ == "__main__":
    main()
