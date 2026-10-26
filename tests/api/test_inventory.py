"""Inventory API tests."""

from datetime import date
from uuid import uuid4

from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _unit_id_by_code(client: AsyncClient, headers: dict[str, str], code: str) -> str:
    response = await client.get(
        "/api/v1/inventory/units",
        headers=headers,
        params={"search": code, "page_size": 50},
    )
    assert response.status_code == 200, response.text
    for row in response.json()["data"]:
        if row["code"] == code:
            return row["id"]
    raise AssertionError(f"Unit {code} not found")


async def _seed_product_micron_sku(
    client: AsyncClient,
    headers: dict[str, str],
) -> tuple[str, str, str]:
    mm_unit_id = await _unit_id_by_code(client, headers, "mm")

    product = await client.post(
        "/api/v1/inventory/material-categories",
        headers=headers,
        json={"name": f"Prod-{uuid4().hex[:6]}"},
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["data"]["id"]

    micron = await client.post(
        "/api/v1/inventory/microns",
        headers=headers,
        json={
            "product_id": product_id,
            "name": "12 MIC",
            "price_per_unit": "25.5",
        },
    )
    assert micron.status_code == 201, micron.text
    micron_id = micron.json()["data"]["id"]
    assert micron.json()["data"]["price_unit_code"] == "kg"

    material = await client.post(
        "/api/v1/inventory/material-subcategories",
        headers=headers,
        json={
            "parent_id": micron_id,
            "size": "300",
            "size_unit_id": mm_unit_id,
            "name": f"Mat-{uuid4().hex[:6]}",
            "opening_rolls": "10",
            "opening_kg": "100",
        },
    )
    assert material.status_code == 201, material.text
    material_id = material.json()["data"]["id"]
    body = material.json()["data"]
    assert body["rolls_on_hand"] == "10.00"
    assert body["total_kg"] == "100.00"
    assert float(body["price_per_unit"]) == 25.5
    assert body["size_unit_code"] == "mm"
    assert body["size_label"] == "300.00 mm"
    return product_id, micron_id, material_id


async def test_inventory_crud_and_movements(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    _, _, material_id = await _seed_product_micron_sku(client, headers)

    today = date.today().isoformat()
    movement_in = await client.post(
        "/api/v1/inventory/material-movements",
        headers=headers,
        json={
            "category_id": material_id,
            "movement_date": today,
            "direction": "IN",
            "rolls": "2",
            "kilograms": "20",
        },
    )
    assert movement_in.status_code == 201, movement_in.text

    material = await client.get(f"/api/v1/inventory/material-subcategories/{material_id}", headers=headers)
    assert material.status_code == 200
    assert float(material.json()["data"]["rolls_on_hand"]) == 12
    assert float(material.json()["data"]["total_kg"]) == 120

    movement_out = await client.post(
        "/api/v1/inventory/material-movements",
        headers=headers,
        json={
            "category_id": material_id,
            "movement_date": today,
            "direction": "OUT",
            "rolls": "15",
            "kilograms": "50",
        },
    )
    assert movement_out.status_code == 409, movement_out.text

    patch_rolls = await client.patch(
        f"/api/v1/inventory/material-subcategories/{material_id}",
        headers=headers,
        json={"rolls_on_hand": "15"},
    )
    assert patch_rolls.status_code == 200, patch_rolls.text
    assert float(patch_rolls.json()["data"]["rolls_on_hand"]) == 15

    patch_kg = await client.patch(
        f"/api/v1/inventory/material-subcategories/{material_id}",
        headers=headers,
        json={"total_kg": "110"},
    )
    assert patch_kg.status_code == 200, patch_kg.text
    assert float(patch_kg.json()["data"]["total_kg"]) == 110

    material = await client.get(f"/api/v1/inventory/material-subcategories/{material_id}", headers=headers)
    assert float(material.json()["data"]["rolls_on_hand"]) == 15
    assert float(material.json()["data"]["total_kg"]) == 110

    report = await client.get(
        "/api/v1/inventory/material-movements/report",
        headers=headers,
        params={"date": today},
    )
    assert report.status_code == 200, report.text
    rows = report.json()["data"]
    assert len(rows) == 1
    assert float(rows[0]["in_rolls"]) == 5
    assert float(rows[0]["closing_rolls"]) == 15
    assert rows[0]["size_label"] == "300.00 mm"


async def test_day_report_lists_all_materials_without_daily_movements(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    await _seed_product_micron_sku(client, headers)

    report = await client.get(
        "/api/v1/inventory/material-movements/report",
        headers=headers,
        params={"date": date.today().isoformat()},
    )
    assert report.status_code == 200, report.text
    rows = report.json()["data"]
    assert len(rows) == 1
    assert float(rows[0]["in_rolls"]) == 0
    assert float(rows[0]["out_rolls"]) == 0
    assert float(rows[0]["closing_rolls"]) == 10
    assert float(rows[0]["closing_kg"]) == 100


async def test_price_hidden_without_permission(client: AsyncClient) -> None:
    admin_email, password = await provision_admin()
    admin_headers = await login_headers(client, admin_email, password)
    _, _, material_id = await _seed_product_micron_sku(client, admin_headers)

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
        json={"name": f"Inv-{uuid4().hex[:6]}", "description": "Material read only"},
    )
    assert role.status_code == 201, role.text
    role_id = role.json()["data"]["id"]
    assign = await client.put(
        f"/api/v1/roles/{role_id}/permissions",
        headers=admin_headers,
        json={"permission_ids": [material_read_id]},
    )
    assert assign.status_code == 200, assign.text

    user_email = f"inv-{uuid4().hex[:8]}@example.com"
    user = await client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "name": "Inventory Reader",
            "email": user_email,
            "password": password,
            "role_ids": [role_id],
        },
    )
    assert user.status_code in {200, 201}, user.text

    user_headers = await login_headers(client, user_email, password)
    response = await client.get(
        f"/api/v1/inventory/material-subcategories/{material_id}",
        headers=user_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["price_per_unit"] is None


async def test_materials_table_preference_accepts_rate_column(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    response = await client.put(
        "/api/v1/users/me/table-preferences/inventory.materials",
        headers=headers,
        json={
            "visible_columns": ["size", "rolls", "total_kg", "price_per_unit"],
            "column_order": ["size", "rolls", "total_kg", "price_per_unit"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert "price_per_unit" in body["visible_columns"]


async def test_materials_report_table_preference_accepts_column_order(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    response = await client.put(
        "/api/v1/users/me/table-preferences/inventory.materials_report",
        headers=headers,
        json={
            "visible_columns": ["size", "in_rolls", "closing_kg", "product"],
            "column_order": ["size", "in_rolls", "closing_kg", "product", "micron"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["is_default"] is False
    assert body["column_order"][:4] == ["size", "in_rolls", "closing_kg", "product"]
