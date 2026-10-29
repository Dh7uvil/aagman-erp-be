"""Inventory dashboard API tests."""

from uuid import uuid4

from httpx import AsyncClient

from tests.api.test_inventory import _seed_product_micron_sku
from tests.api.test_jobs import _create_company, _job_payload
from tests.conftest import login_headers, provision_admin


async def test_jobs_dashboard_kpis_and_awaiting_return(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    company_id = await _create_company(client, headers)

    create_active = await client.post(
        "/api/v1/inventory/jobs",
        headers=headers,
        json=_job_payload(company_id),
    )
    assert create_active.status_code == 201, create_active.text
    active_job_id = create_active.json()["data"]["id"]

    completed_payload = _job_payload(company_id)
    completed_payload["product_name"] = "Completed film"
    completed_payload["status"] = "COMPLETED"
    create_completed = await client.post(
        "/api/v1/inventory/jobs",
        headers=headers,
        json=completed_payload,
    )
    assert create_completed.status_code == 201, create_completed.text

    dashboard = await client.get("/api/v1/inventory/dashboard/jobs", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()["data"]
    assert body["kpis"]["active_jobs"] >= 1
    assert body["kpis"]["cylinders_in_circulation"] >= 4
    assert body["kpis"]["awaiting_return"] >= 1
    assert body["kpis"]["cylinder_cost_exposure"] is not None

    statuses = {row["status"]: row["count"] for row in body["status_breakdown"]}
    assert statuses.get("ACTIVE", 0) >= 1
    assert statuses.get("COMPLETED", 0) >= 1

    pause = await client.post(
        f"/api/v1/inventory/jobs/{active_job_id}/pause",
        headers=headers,
        json={"pause_remarks": "Hold"},
    )
    assert pause.status_code == 200, pause.text

    after_pause = await client.get("/api/v1/inventory/dashboard/jobs", headers=headers)
    assert after_pause.json()["data"]["kpis"]["paused_jobs"] >= 1
    assert len(after_pause.json()["data"]["open_pauses"]) >= 1


async def test_materials_dashboard_and_price_masking(client: AsyncClient) -> None:
    admin_email, password = await provision_admin()
    admin_headers = await login_headers(client, admin_email, password)
    await _seed_product_micron_sku(client, admin_headers)

    admin_resp = await client.get("/api/v1/inventory/dashboard/materials", headers=admin_headers)
    assert admin_resp.status_code == 200, admin_resp.text
    admin_body = admin_resp.json()["data"]
    assert admin_body["kpis"]["active_skus"] >= 1
    assert float(admin_body["kpis"]["total_kg_on_hand"]) >= 100
    assert admin_body["kpis"]["stock_value"] is not None
    assert admin_body["kpis"]["valued_sku_count"] >= 1
    assert len(admin_body["stock_by_product"]) >= 1

    matrix = await client.get("/api/v1/permissions/matrix", headers=admin_headers)
    assert matrix.status_code == 200
    inventory_perms = [
        action
        for mod in matrix.json()["data"]["modules"]
        if mod["module"] == "inventory"
        for resource in mod["resources"]
        for action in resource["actions"]
    ]
    material_read_id = next(
        item["id"] for item in inventory_perms if item["code"] == "inventory.material.read"
    )

    role = await client.post(
        "/api/v1/roles",
        headers=admin_headers,
        json={"name": f"Dash-{uuid4().hex[:6]}", "description": "Material read only"},
    )
    assert role.status_code == 201, role.text
    role_id = role.json()["data"]["id"]
    assign = await client.put(
        f"/api/v1/roles/{role_id}/permissions",
        headers=admin_headers,
        json={"permission_ids": [material_read_id]},
    )
    assert assign.status_code == 200, assign.text

    user_email = f"dash-{uuid4().hex[:8]}@example.com"
    user = await client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "name": "Dashboard Reader",
            "email": user_email,
            "password": password,
            "role_ids": [role_id],
        },
    )
    assert user.status_code in {200, 201}, user.text

    user_headers = await login_headers(client, user_email, password)
    masked = await client.get("/api/v1/inventory/dashboard/materials", headers=user_headers)
    assert masked.status_code == 200, masked.text
    assert masked.json()["data"]["kpis"]["stock_value"] is None
    assert masked.json()["data"]["kpis"]["valued_sku_count"] == 0
