"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient

_TEST_ENV_PATH = Path(__file__).resolve().parents[1] / ".env.test"
if _TEST_ENV_PATH.is_file():
    load_dotenv(_TEST_ENV_PATH, override=True)

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()
_SETTINGS = get_settings()

ADMIN_PASSWORD = "Password12"


@pytest.fixture(scope="session", autouse=True)
def ensure_test_db_migrated() -> None:
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")


@pytest.fixture
def app():
    from app.main import create_app

    return create_app()


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as http:
        yield http


async def _reset_identity_tables() -> None:
    from sqlalchemy import text

    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE user_table_preferences, user_roles, role_permissions, "
                "refresh_tokens, password_reset_tokens, audit_logs, users, departments, "
                "warehouses, branches, roles, permissions, organizations, addresses, "
                "material_movements, material_categories, inventory_units, "
                "job_colors, job_cylinders, job_pauses, cylinder_returns, jobs, "
                "companies "
                "RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()


async def provision_admin(*, name: str | None = None) -> tuple[str, str]:
    from app.cli.bootstrap import provision_organization
    from app.core.security import hash_password

    suffix = uuid4().hex[:8]
    org_name = name or f"Test Org {suffix}"
    admin_email = f"admin-{suffix}@example.com"

    await _reset_identity_tables()

    result = await provision_organization(
        organization_name=org_name,
        admin_name="Admin User",
        admin_email=admin_email,
        password_hash=hash_password(ADMIN_PASSWORD),
    )
    return admin_email, ADMIN_PASSWORD


async def login_headers(
    client: AsyncClient,
    email: str,
    password: str = ADMIN_PASSWORD,
) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}
