"""Inventory dashboard API tests."""

from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import update

from tests.api.test_inventory import (
    _create_company,
    _seed_product_micron_sku,
    _unit_id_by_code,
)
from tests.api.test_cylinders import _cylinder_payload
from tests.conftest import login_headers, provision_admin


async def _backdate_sku_activity(material_id: str, *, days_ago: int) -> None:
    from app.db.session import async_session_factory
    from app.inventory.models import MaterialCategory, MaterialMovement

    target_date = date.today() - timedelta(days=days_ago)
    target_dt = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    sku_id = UUID(material_id)

    async with async_session_factory() as session:
        await session.execute(
            update(MaterialCategory)
            .where(MaterialCategory.id == sku_id)
            .values(created_at=target_dt, updated_at=target_dt)
        )
        await session.execute(
            update(MaterialMovement)
            .where(
                MaterialMovement.category_id == sku_id,
                MaterialMovement.deleted_at.is_(None),
            )
            .values(
                movement_date=target_date,
                created_at=target_dt,
                updated_at=target_dt,
            )
        )
        await session.commit()


async def _create_sku_with_opening(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    opening_kg: str,
    opening_rolls: str = "0",
) -> str:
    mm_unit_id = await _unit_id_by_code(client, headers, "mm")
    company_id = await _create_company(client, headers)
    product = await client.post(
        "/api/v1/inventory/material-categories",
        headers=headers,
        json={"name": f"Prod-{uuid4().hex[:6]}", "company_id": company_id},
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["data"]["id"]
    micron = await client.post(
        "/api/v1/inventory/microns",
        headers=headers,
        json={"product_id": product_id, "name": "12 MIC"},
    )
    assert micron.status_code == 201, micron.text
    micron_id = micron.json()["data"]["id"]
    material = await client.post(
        "/api/v1/inventory/material-subcategories",
        headers=headers,
        json={
            "parent_id": micron_id,
            "size": "300",
            "size_unit_id": mm_unit_id,
            "name": f"Mat-{uuid4().hex[:6]}",
            "opening_rolls": opening_rolls,
            "opening_kg": opening_kg,
        },
    )
    assert material.status_code == 201, material.text
    return material.json()["data"]["id"]


async def test_cylinders_dashboard_kpis_and_awaiting_return(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    company_id = await _create_company(client, headers)

    active_payload = _cylinder_payload(company_id)
    active_payload["cylinder_cost"] = "150.50"
    create_active = await client.post(
        "/api/v1/inventory/cylinders",
        headers=headers,
        json=active_payload,
    )
    assert create_active.status_code == 201, create_active.text
    active_cylinder_id = create_active.json()["data"]["id"]

    completed_payload = _cylinder_payload(company_id)
    completed_payload["product_name"] = "Completed film"
    completed_payload["status"] = "COMPLETED"
    completed_payload["cylinder_cost"] = "80.00"
    create_completed = await client.post(
        "/api/v1/inventory/cylinders",
        headers=headers,
        json=completed_payload,
    )
    assert create_completed.status_code == 201, create_completed.text
    completed_cylinder_id = create_completed.json()["data"]["id"]

    dashboard = await client.get("/api/v1/inventory/dashboard/cylinders", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()["data"]
    assert body["kpis"]["active_cylinders"] >= 1
    assert body["kpis"]["cylinders_in_circulation"] == 0
    assert body["kpis"]["awaiting_return"] >= 1
    assert float(body["kpis"]["cylinder_cost_exposure"]) == 301.0

    create_return = await client.post(
        "/api/v1/inventory/cylinder-returns",
        headers=headers,
        json={"cylinder_id": completed_cylinder_id, "company_id": company_id},
    )
    assert create_return.status_code == 201, create_return.text

    after_return = await client.get("/api/v1/inventory/dashboard/cylinders", headers=headers)
    assert after_return.status_code == 200, after_return.text
    assert after_return.json()["data"]["kpis"]["cylinders_in_circulation"] == 2

    statuses = {row["status"]: row["count"] for row in body["status_breakdown"]}
    assert statuses.get("ACTIVE", 0) >= 1
    assert statuses.get("COMPLETED", 0) >= 1

    pause = await client.post(
        f"/api/v1/inventory/cylinders/{active_cylinder_id}/pause",
        headers=headers,
        json={"pause_remarks": "Hold"},
    )
    assert pause.status_code == 200, pause.text

    after_pause = await client.get("/api/v1/inventory/dashboard/cylinders", headers=headers)
    assert after_pause.json()["data"]["kpis"]["paused_cylinders"] >= 1
    assert float(after_pause.json()["data"]["kpis"]["cylinder_cost_exposure"]) == 0
    assert len(after_pause.json()["data"]["open_pauses"]) >= 1


async def test_cylinders_dashboard_cost_requires_view_price(client: AsyncClient) -> None:
    admin_email, password = await provision_admin()
    admin_headers = await login_headers(client, admin_email, password)
    company_id = await _create_company(client, admin_headers)

    payload = _cylinder_payload(company_id)
    payload["cylinder_cost"] = "25.00"
    created = await client.post("/api/v1/inventory/cylinders", headers=admin_headers, json=payload)
    assert created.status_code == 201, created.text

    admin_resp = await client.get("/api/v1/inventory/dashboard/cylinders", headers=admin_headers)
    assert admin_resp.status_code == 200, admin_resp.text
    assert float(admin_resp.json()["data"]["kpis"]["cylinder_cost_exposure"]) == 50.0

    matrix = await client.get("/api/v1/permissions/matrix", headers=admin_headers)
    assert matrix.status_code == 200
    inventory_perms = [
        action
        for mod in matrix.json()["data"]["modules"]
        if mod["module"] == "inventory"
        for resource in mod["resources"]
        for action in resource["actions"]
    ]
    cylinder_read_id = next(
        item["id"] for item in inventory_perms if item["code"] == "inventory.cylinder.read"
    )

    role = await client.post(
        "/api/v1/roles",
        headers=admin_headers,
        json={"name": f"Cyl-{uuid4().hex[:6]}", "description": "Cylinder read only"},
    )
    assert role.status_code == 201, role.text
    role_id = role.json()["data"]["id"]
    assign = await client.put(
        f"/api/v1/roles/{role_id}/permissions",
        headers=admin_headers,
        json={"permission_ids": [cylinder_read_id]},
    )
    assert assign.status_code == 200, assign.text

    user_email = f"cyl-{uuid4().hex[:8]}@example.com"
    user = await client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "name": "Cylinder Reader",
            "email": user_email,
            "password": password,
            "role_ids": [role_id],
        },
    )
    assert user.status_code in {200, 201}, user.text

    user_headers = await login_headers(client, user_email, password)
    masked = await client.get("/api/v1/inventory/dashboard/cylinders", headers=user_headers)
    assert masked.status_code == 200, masked.text
    assert masked.json()["data"]["kpis"]["cylinder_cost_exposure"] is None


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
    assert isinstance(admin_body["kpis"]["dead_stock_skus"], int)
    assert isinstance(admin_body["dead_stock"], list)
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


async def test_materials_dashboard_dead_stock(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)

    fresh_id = await _create_sku_with_opening(client, headers, opening_kg="50", opening_rolls="5")
    idle_id = await _create_sku_with_opening(client, headers, opening_kg="80", opening_rolls="8")
    await _backdate_sku_activity(idle_id, days_ago=61)

    zero_kg_id = await _create_sku_with_opening(client, headers, opening_kg="0", opening_rolls="0")
    await _backdate_sku_activity(zero_kg_id, days_ago=61)

    cleared_id = await _create_sku_with_opening(client, headers, opening_kg="40", opening_rolls="4")
    await _backdate_sku_activity(cleared_id, days_ago=61)
    today = date.today().isoformat()
    recent_out = await client.post(
        "/api/v1/inventory/material-movements",
        headers=headers,
        json={
            "category_id": cleared_id,
            "movement_date": today,
            "direction": "OUT",
            "rolls": "1",
            "kilograms": "1",
        },
    )
    assert recent_out.status_code == 201, recent_out.text

    dashboard = await client.get("/api/v1/inventory/dashboard/materials", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()["data"]
    dead_ids = {row["material_id"] for row in body["dead_stock"]}

    assert fresh_id not in dead_ids
    assert zero_kg_id not in dead_ids
    assert cleared_id not in dead_ids
    assert idle_id in dead_ids

    idle_row = next(row for row in body["dead_stock"] if row["material_id"] == idle_id)
    assert idle_row["days_idle"] == 61
    assert idle_row["last_activity_date"] == (date.today() - timedelta(days=61)).isoformat()
    assert float(idle_row["total_kg"]) == 80.0
    assert body["kpis"]["dead_stock_skus"] == len(body["dead_stock"])
    assert body["kpis"]["dead_stock_skus"] >= 1
