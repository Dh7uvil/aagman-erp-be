"""Identity, org structure, audit, and table preference API tests."""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.enums import AuditStatus, UserStatus
from app.db.session import async_session_factory
from app.common.models.audit_log import AuditLog
from app.identity.models import User
from tests.conftest import ADMIN_PASSWORD, login_headers, provision_admin


async def _count_audit(
    *,
    action: str | None = None,
    status: str | None = None,
    entity_type: str | None = None,
) -> int:
    async with async_session_factory() as session:
        stmt = select(AuditLog)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if status is not None:
            stmt = stmt.where(AuditLog.status == status)
        if entity_type is not None:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        result = await session.execute(stmt)
        return len(result.scalars().all())


async def test_login_success_audit_row(client: AsyncClient) -> None:
    email, password = await provision_admin()
    before = await _count_audit(action="LOGIN", status=AuditStatus.SUCCESS)
    await login_headers(client, email, password)
    after = await _count_audit(action="LOGIN", status=AuditStatus.SUCCESS)
    assert after == before + 1


async def test_login_failure_audit_row(client: AsyncClient) -> None:
    email, _ = await provision_admin()
    before = await _count_audit(action="LOGIN", status=AuditStatus.FAILED)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WrongPassword1"},
    )
    assert response.status_code == 401
    after = await _count_audit(action="LOGIN", status=AuditStatus.FAILED)
    assert after == before + 1


async def test_disabled_user_cannot_login(client: AsyncClient) -> None:
    admin_email, password = await provision_admin()
    headers = await login_headers(client, admin_email, password)
    target_email = f"disabled-{uuid4().hex[:8]}@example.com"
    create = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Disabled User",
            "email": target_email,
            "password": ADMIN_PASSWORD,
        },
    )
    assert create.status_code in {200, 201}, create.text
    user_id = create.json()["data"]["id"]
    deactivate = await client.post(f"/api/v1/users/{user_id}/deactivate", headers=headers)
    assert deactivate.status_code == 200, deactivate.text

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": target_email, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 401


async def test_organization_branding_is_public(client: AsyncClient) -> None:
    response = await client.get("/api/v1/organization/branding")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"]


_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def test_organization_logo_is_public(client: AsyncClient) -> None:
    branding = await client.get("/api/v1/organization/branding")
    assert branding.status_code == 200, branding.text
    logo_url = branding.json()["data"].get("logo_url")
    if logo_url is None:
        pytest.skip("organization has no logo")
    response = await client.get(logo_url)
    assert response.status_code == 200, response.text
    assert response.headers.get("content-type", "").startswith("image/")
    assert "no-cache" in (response.headers.get("cache-control") or "").lower()


async def test_organization_logo_upload_changes_url(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)

    first = await client.post(
        "/api/v1/organization/logo",
        headers=headers,
        files={"file": ("logo.png", _TINY_PNG, "image/png")},
    )
    assert first.status_code == 200, first.text
    first_url = first.json()["data"]["logo_url"]
    assert first_url
    assert "v=" in first_url

    fetched = await client.get(first_url)
    assert fetched.status_code == 200, fetched.text
    assert fetched.headers.get("content-type", "").startswith("image/")

    second = await client.post(
        "/api/v1/organization/logo",
        headers=headers,
        files={"file": ("logo.png", _TINY_PNG, "image/png")},
    )
    assert second.status_code == 200, second.text
    second_url = second.json()["data"]["logo_url"]
    assert second_url != first_url


async def test_organization_singleton_update(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    before = await _count_audit(action="UPDATE", status=AuditStatus.SUCCESS)

    response = await client.patch(
        "/api/v1/organization",
        headers=headers,
        json={"name": "Aagman Test Org", "timezone": "Asia/Dubai"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["name"] == "Aagman Test Org"

    after = await _count_audit(action="UPDATE", status=AuditStatus.SUCCESS)
    assert after >= before + 1


async def test_branch_create_writes_audit(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    before = await _count_audit(action="CREATE", entity_type="branch")

    code = f"BR-{uuid4().hex[:6].upper()}"
    response = await client.post(
        "/api/v1/branches",
        headers=headers,
        json={"name": "Main Office", "code": code, "status": "ACTIVE"},
    )
    assert response.status_code == 201, response.text

    after = await _count_audit(action="CREATE", entity_type="branch")
    assert after == before + 1


async def test_department_and_warehouse_create(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)

    branch_code = f"BR-{uuid4().hex[:6].upper()}"
    branch = await client.post(
        "/api/v1/branches",
        headers=headers,
        json={"name": "HQ", "code": branch_code, "status": "ACTIVE"},
    )
    assert branch.status_code == 201, branch.text
    branch_id = branch.json()["data"]["id"]

    dept_code = f"DP-{uuid4().hex[:6].upper()}"
    department = await client.post(
        "/api/v1/departments",
        headers=headers,
        json={"name": "Engineering", "code": dept_code, "branch_id": branch_id},
    )
    assert department.status_code == 201, department.text

    wh_code = f"WH-{uuid4().hex[:6].upper()}"
    warehouse = await client.post(
        "/api/v1/warehouses",
        headers=headers,
        json={"name": "Default Store", "code": wh_code, "is_active": True},
    )
    assert warehouse.status_code == 201, warehouse.text


async def test_permission_denied_for_users_without_grant(client: AsyncClient) -> None:
    admin_email, password = await provision_admin()
    admin_headers = await login_headers(client, admin_email, password)

    role_response = await client.post(
        "/api/v1/roles",
        headers=admin_headers,
        json={"name": f"AuditOnly-{uuid4().hex[:6]}", "description": "Read audit logs only"},
    )
    assert role_response.status_code == 201, role_response.text
    role_id = role_response.json()["data"]["id"]

    matrix = await client.get(
        f"/api/v1/permissions/matrix?role_id={role_id}",
        headers=admin_headers,
    )
    assert matrix.status_code == 200, matrix.text
    audit_read_id = None
    for module in matrix.json()["data"]["modules"]:
        if module["module"] != "identity":
            continue
        for resource in module["resources"]:
            if resource["resource"] != "audit_log":
                continue
            for action in resource["actions"]:
                if action["action"] == "read":
                    audit_read_id = action["id"]
                    break
    assert audit_read_id is not None
    assign = await client.put(
        f"/api/v1/roles/{role_id}/permissions",
        headers=admin_headers,
        json={"permission_ids": [audit_read_id]},
    )
    assert assign.status_code == 200, assign.text

    viewer_email = f"viewer-{uuid4().hex[:8]}@example.com"
    create_user = await client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "name": "Audit Viewer",
            "email": viewer_email,
            "password": ADMIN_PASSWORD,
            "role_ids": [role_id],
        },
    )
    assert create_user.status_code in {200, 201}, create_user.text

    viewer_headers = await login_headers(client, viewer_email, password)
    audit_list = await client.get("/api/v1/audit-logs", headers=viewer_headers)
    assert audit_list.status_code == 200

    reference_lists = [
        "/api/v1/users",
        "/api/v1/roles",
        "/api/v1/branches",
        "/api/v1/departments",
        "/api/v1/inventory/units",
        "/api/v1/inventory/material-categories",
        "/api/v1/inventory/microns",
    ]
    for path in reference_lists:
        listed = await client.get(path, headers=viewer_headers)
        assert listed.status_code == 200, f"{path}: {listed.text}"

    denied = await client.post(
        "/api/v1/users",
        headers=viewer_headers,
        json={
            "name": "Should Fail",
            "email": f"fail-{uuid4().hex[:8]}@example.com",
            "password": ADMIN_PASSWORD,
        },
    )
    assert denied.status_code == 403


async def test_table_preference_unknown_key_404(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    response = await client.get(
        "/api/v1/users/me/table-preferences/identity.unknown_table",
        headers=headers,
    )
    assert response.status_code == 404


async def test_table_preference_rejects_unknown_column(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    response = await client.put(
        "/api/v1/users/me/table-preferences/identity.users",
        headers=headers,
        json={
            "visible_columns": ["email", "not_a_real_column"],
            "column_order": ["email", "not_a_real_column"],
        },
    )
    assert response.status_code == 422


async def test_table_preference_reset_returns_defaults(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    save = await client.put(
        "/api/v1/users/me/table-preferences/identity.roles",
        headers=headers,
        json={
            "visible_columns": ["name", "description"],
            "column_order": ["name", "description", "type"],
        },
    )
    assert save.status_code == 200
    assert save.json()["data"]["is_default"] is False

    reset = await client.delete(
        "/api/v1/users/me/table-preferences/identity.roles",
        headers=headers,
    )
    assert reset.status_code == 200
    assert reset.json()["data"]["is_default"] is True


async def test_cannot_remove_last_superadmin_role(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    me = await client.get("/api/v1/auth/me", headers=headers)
    user_id = me.json()["data"]["id"]
    roles = await client.get("/api/v1/roles", headers=headers)
    superadmin = next(row for row in roles.json()["data"] if row["name"] == "Superadmin")
    response = await client.put(
        f"/api/v1/users/{user_id}/roles",
        headers=headers,
        json={"role_ids": []},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/audit-logs"),
        ("PUT", "/api/v1/audit-logs/00000000-0000-0000-0000-000000000001"),
    ],
)
async def test_audit_logs_are_read_only(
    client: AsyncClient,
    method: str,
    path: str,
) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    response = await client.request(method, path, headers=headers, json={})
    assert response.status_code == 405


async def test_company_crud_duplicate_name_and_permission(client: AsyncClient) -> None:
    admin_email, password = await provision_admin()
    admin_headers = await login_headers(client, admin_email, password)
    name = f"Acme-{uuid4().hex[:6]}"

    create = await client.post(
        "/api/v1/companies",
        headers=admin_headers,
        json={
            "name": name,
            "email": "contact@acme.example",
            "phone": "+1-555-0100",
            "address": {
                "address_line_1": "1 Market St",
                "city": "San Francisco",
                "country_code": "US",
            },
            "bill_to_address": {
                "address_line_1": "1 Market St",
                "city": "San Francisco",
                "country_code": "US",
            },
            "ship_to_address": {
                "address_line_1": "99 Ship Lane",
                "city": "Oakland",
                "country_code": "US",
            },
        },
    )
    assert create.status_code == 201, create.text
    company_id = create.json()["data"]["id"]
    assert create.json()["data"]["name"] == name
    assert create.json()["data"]["email"] == "contact@acme.example"
    assert create.json()["data"]["bill_to_address"]["city"] == "San Francisco"
    assert create.json()["data"]["ship_to_address"]["city"] == "Oakland"

    before = await _count_audit(action="CREATE", entity_type="company")
    duplicate = await client.post(
        "/api/v1/companies",
        headers=admin_headers,
        json={"name": name},
    )
    assert duplicate.status_code == 409, duplicate.text
    after = await _count_audit(action="CREATE", entity_type="company")
    assert after == before

    listed = await client.get("/api/v1/companies", headers=admin_headers)
    assert listed.status_code == 200
    assert any(row["id"] == company_id for row in listed.json()["data"])

    detail = await client.get(f"/api/v1/companies/{company_id}", headers=admin_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["address"]["city"] == "San Francisco"

    updated = await client.patch(
        f"/api/v1/companies/{company_id}",
        headers=admin_headers,
        json={"phone": "+1-555-0199"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["phone"] == "+1-555-0199"

    deleted = await client.delete(f"/api/v1/companies/{company_id}", headers=admin_headers)
    assert deleted.status_code == 200

    role_response = await client.post(
        "/api/v1/roles",
        headers=admin_headers,
        json={"name": f"NoCompany-{uuid4().hex[:6]}", "description": "No company create"},
    )
    assert role_response.status_code == 201, role_response.text
    role_id = role_response.json()["data"]["id"]

    matrix = await client.get(
        f"/api/v1/permissions/matrix?role_id={role_id}",
        headers=admin_headers,
    )
    assert matrix.status_code == 200, matrix.text
    company_read_id = None
    for module in matrix.json()["data"]["modules"]:
        if module["module"] != "identity":
            continue
        for resource in module["resources"]:
            if resource["resource"] != "company":
                continue
            for action in resource["actions"]:
                if action["action"] == "read":
                    company_read_id = action["id"]
                    break
    assert company_read_id is not None
    assign = await client.put(
        f"/api/v1/roles/{role_id}/permissions",
        headers=admin_headers,
        json={"permission_ids": [company_read_id]},
    )
    assert assign.status_code == 200, assign.text

    viewer_email = f"company-viewer-{uuid4().hex[:8]}@example.com"
    create_user = await client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "name": "Company Viewer",
            "email": viewer_email,
            "password": ADMIN_PASSWORD,
            "role_ids": [role_id],
        },
    )
    assert create_user.status_code in {200, 201}, create_user.text
    viewer_headers = await login_headers(client, viewer_email, password)

    can_list = await client.get("/api/v1/companies", headers=viewer_headers)
    assert can_list.status_code == 200

    denied = await client.post(
        "/api/v1/companies",
        headers=viewer_headers,
        json={"name": f"Blocked-{uuid4().hex[:6]}"},
    )
    assert denied.status_code == 403


async def test_user_status_disabled_in_database(client: AsyncClient) -> None:
    admin_email, password = await provision_admin()
    headers = await login_headers(client, admin_email, password)
    target_email = f"to-disable-{uuid4().hex[:8]}@example.com"
    create = await client.post(
        "/api/v1/users",
        headers=headers,
        json={"name": "Temp", "email": target_email, "password": ADMIN_PASSWORD},
    )
    user_id = create.json()["data"]["id"]
    deactivate = await client.post(f"/api/v1/users/{user_id}/deactivate", headers=headers)
    assert deactivate.status_code == 200
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        assert user.status == UserStatus.DISABLED
