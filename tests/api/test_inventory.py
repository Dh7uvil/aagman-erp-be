"""Inventory API tests."""

from datetime import date, timedelta
from uuid import uuid4

from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _create_company(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/companies",
        headers=headers,
        json={"name": f"Co-{uuid4().hex[:8]}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


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


async def test_material_skus_save_under_correct_microns(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    mm_unit_id = await _unit_id_by_code(client, headers, "mm")
    company_id = await _create_company(client, headers)

    product = await client.post(
        "/api/v1/inventory/material-categories",
        headers=headers,
        json={"name": f"Prod-{uuid4().hex[:6]}", "company_id": company_id},
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["data"]["id"]

    micron_a = await client.post(
        "/api/v1/inventory/microns",
        headers=headers,
        json={"product_id": product_id, "name": "12 MIC"},
    )
    micron_b = await client.post(
        "/api/v1/inventory/microns",
        headers=headers,
        json={"product_id": product_id, "name": "18 MIC"},
    )
    assert micron_a.status_code == 201, micron_a.text
    assert micron_b.status_code == 201, micron_b.text
    micron_a_id = micron_a.json()["data"]["id"]
    micron_b_id = micron_b.json()["data"]["id"]

    sku_a = await client.post(
        "/api/v1/inventory/material-subcategories",
        headers=headers,
        json={
            "parent_id": micron_a_id,
            "size": "300",
            "size_unit_id": mm_unit_id,
        },
    )
    sku_b = await client.post(
        "/api/v1/inventory/material-subcategories",
        headers=headers,
        json={
            "parent_id": micron_b_id,
            "size": "300",
            "size_unit_id": mm_unit_id,
        },
    )
    assert sku_a.status_code == 201, sku_a.text
    assert sku_b.status_code == 201, sku_b.text
    sku_a_id = sku_a.json()["data"]["id"]

    listed = await client.get(
        "/api/v1/inventory/material-subcategories",
        headers=headers,
        params={"product_id": product_id, "page_size": 50},
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()["data"]
    assert len(rows) == 2
    micron_ids = {row["micron_id"] for row in rows}
    assert micron_ids == {micron_a_id, micron_b_id}

    moved = await client.patch(
        f"/api/v1/inventory/material-subcategories/{sku_a_id}",
        headers=headers,
        json={"parent_id": micron_b_id, "size": "350"},
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()["data"]
    assert body["micron_id"] == micron_b_id
    assert float(body["size"]) == 350


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


async def test_incoming_movement_stores_purchase_price(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    _product_id, micron_id, material_id = await _seed_product_micron_sku(client, headers)

    micron = await client.get(f"/api/v1/inventory/microns/{micron_id}", headers=headers)
    assert micron.status_code == 200, micron.text
    price_unit_id = micron.json()["data"]["price_unit_id"]

    today = date.today().isoformat()
    movement_in = await client.post(
        "/api/v1/inventory/material-movements",
        headers=headers,
        json={
            "category_id": material_id,
            "movement_date": today,
            "direction": "IN",
            "rolls": "3",
            "kilograms": "0",
            "price_per_unit": "99.5",
            "price_unit_id": price_unit_id,
            "note": "New purchase batch",
        },
    )
    assert movement_in.status_code == 201, movement_in.text

    history = await client.get(
        f"/api/v1/inventory/material-subcategories/{material_id}/history",
        headers=headers,
    )
    assert history.status_code == 200
    stock_rows = [row for row in history.json()["data"] if row["kind"] == "stock" and row["action"] == "IN"]
    assert any(float(row["price_per_unit"]) == 99.5 for row in stock_rows)

    micron_after = await client.get(f"/api/v1/inventory/microns/{micron_id}", headers=headers)
    assert float(micron_after.json()["data"]["price_per_unit"]) == 99.5


async def test_material_history_keeps_purchase_price_when_micron_price_changes(
    client: AsyncClient,
) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    _product_id, micron_id, material_id = await _seed_product_micron_sku(client, headers)

    micron = await client.get(f"/api/v1/inventory/microns/{micron_id}", headers=headers)
    price_unit_id = micron.json()["data"]["price_unit_id"]
    today = date.today().isoformat()

    purchase = await client.post(
        "/api/v1/inventory/material-movements",
        headers=headers,
        json={
            "category_id": material_id,
            "movement_date": today,
            "direction": "IN",
            "rolls": "2",
            "kilograms": "0",
            "price_per_unit": "88",
            "price_unit_id": price_unit_id,
        },
    )
    assert purchase.status_code == 201, purchase.text

    micron_update = await client.patch(
        f"/api/v1/inventory/microns/{micron_id}",
        headers=headers,
        json={"price_per_unit": "150", "price_unit_id": price_unit_id},
    )
    assert micron_update.status_code == 200, micron_update.text

    history = await client.get(
        f"/api/v1/inventory/material-subcategories/{material_id}/history",
        headers=headers,
        params={"page_size": 50},
    )
    assert history.status_code == 200, history.text
    stock_rows = history.json()["data"]
    assert all(row["action"] in ("IN", "OUT") for row in stock_rows)
    last_in = next(row for row in stock_rows if row["action"] == "IN" and float(row["rolls"]) == 2)
    assert float(last_in["price_per_unit"]) == 88

    summary = await client.get(
        f"/api/v1/inventory/material-subcategories/{material_id}/history-summary",
        headers=headers,
    )
    assert summary.status_code == 200, summary.text
    assert float(summary.json()["data"]["last_purchase_price"]) == 88


async def test_movement_report_date_range(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    _product_id, _micron_id, material_id = await _seed_product_micron_sku(client, headers)

    day1 = (date.today() - timedelta(days=2)).isoformat()
    day2 = (date.today() - timedelta(days=1)).isoformat()

    movement_in = await client.post(
        "/api/v1/inventory/material-movements",
        headers=headers,
        json={
            "category_id": material_id,
            "movement_date": day1,
            "direction": "IN",
            "rolls": "3",
            "kilograms": "0",
        },
    )
    assert movement_in.status_code == 201, movement_in.text

    movement_out = await client.post(
        "/api/v1/inventory/material-movements",
        headers=headers,
        json={
            "category_id": material_id,
            "movement_date": day2,
            "direction": "OUT",
            "rolls": "1",
            "kilograms": "0",
        },
    )
    assert movement_out.status_code == 201, movement_out.text

    range_report = await client.get(
        "/api/v1/inventory/material-movements/report",
        headers=headers,
        params={"start_date": day1, "end_date": day2},
    )
    assert range_report.status_code == 200, range_report.text
    row = next(row for row in range_report.json()["data"] if row["category_id"] == material_id)
    assert float(row["in_rolls"]) == 3
    assert float(row["out_rolls"]) == 1
    assert float(row["closing_rolls"]) == 12

    single_day = await client.get(
        "/api/v1/inventory/material-movements/report",
        headers=headers,
        params={"date": day2},
    )
    assert single_day.status_code == 200, single_day.text
    day2_row = next(row for row in single_day.json()["data"] if row["category_id"] == material_id)
    assert float(day2_row["in_rolls"]) == 0
    assert float(day2_row["out_rolls"]) == 1
    assert float(day2_row["closing_rolls"]) == 12

    same_day_range = await client.get(
        "/api/v1/inventory/material-movements/report",
        headers=headers,
        params={"start_date": day2, "end_date": day2},
    )
    assert same_day_range.status_code == 200, same_day_range.text
    range_day2_row = next(
        row for row in same_day_range.json()["data"] if row["category_id"] == material_id
    )
    assert float(range_day2_row["in_rolls"]) == float(day2_row["in_rolls"])
    assert float(range_day2_row["out_rolls"]) == float(day2_row["out_rolls"])
    assert float(range_day2_row["closing_rolls"]) == float(day2_row["closing_rolls"])


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


async def test_avg_price_and_stock_valuation_with_multiple_purchases(
    client: AsyncClient,
) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    _product_id, micron_id, material_id = await _seed_product_micron_sku(client, headers)

    micron = await client.get(f"/api/v1/inventory/microns/{micron_id}", headers=headers)
    price_unit_id = micron.json()["data"]["price_unit_id"]
    today = date.today().isoformat()

    second_in = await client.post(
        "/api/v1/inventory/material-movements",
        headers=headers,
        json={
            "category_id": material_id,
            "movement_date": today,
            "direction": "IN",
            "rolls": "0",
            "kilograms": "50",
            "price_per_unit": "150",
            "price_unit_id": price_unit_id,
        },
    )
    assert second_in.status_code == 201, second_in.text

    material = await client.get(
        f"/api/v1/inventory/material-subcategories/{material_id}",
        headers=headers,
    )
    assert material.status_code == 200, material.text
    body = material.json()["data"]
    assert float(body["price_per_unit"]) == 150
    assert float(body["avg_price_per_unit"]) == 67.0

    report = await client.get(
        "/api/v1/inventory/material-movements/report",
        headers=headers,
        params={"date": today},
    )
    assert report.status_code == 200, report.text
    row = next(r for r in report.json()["data"] if r["category_id"] == material_id)
    assert float(row["price_per_unit"]) == 150
    assert float(row["avg_price_per_unit"]) == 67.0

    dashboard = await client.get("/api/v1/inventory/dashboard/materials", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    assert float(dashboard.json()["data"]["kpis"]["stock_value"]) == 10050.0


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


async def test_product_name_unique_per_company(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    company_a = await _create_company(client, headers)
    company_b = await _create_company(client, headers)
    name = f"Shared-{uuid4().hex[:6]}"

    first = await client.post(
        "/api/v1/inventory/material-categories",
        headers=headers,
        json={"name": name, "company_id": company_a},
    )
    second = await client.post(
        "/api/v1/inventory/material-categories",
        headers=headers,
        json={"name": name, "company_id": company_b},
    )
    duplicate = await client.post(
        "/api/v1/inventory/material-categories",
        headers=headers,
        json={"name": name, "company_id": company_a},
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert duplicate.status_code == 409, duplicate.text


async def test_material_list_filter_by_company(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    company_a = await _create_company(client, headers)
    company_b = await _create_company(client, headers)
    mm_unit_id = await _unit_id_by_code(client, headers, "mm")

    async def seed_for_company(company_id: str, label: str) -> str:
        product = await client.post(
            "/api/v1/inventory/material-categories",
            headers=headers,
            json={"name": f"Prod-{label}-{uuid4().hex[:4]}", "company_id": company_id},
        )
        assert product.status_code == 201, product.text
        product_id = product.json()["data"]["id"]
        micron = await client.post(
            "/api/v1/inventory/microns",
            headers=headers,
            json={"product_id": product_id, "name": f"12 MIC {label}"},
        )
        assert micron.status_code == 201, micron.text
        material = await client.post(
            "/api/v1/inventory/material-subcategories",
            headers=headers,
            json={"parent_id": micron.json()["data"]["id"], "size": "300", "size_unit_id": mm_unit_id},
        )
        assert material.status_code == 201, material.text
        return material.json()["data"]["id"]

    material_a = await seed_for_company(company_a, "A")
    await seed_for_company(company_b, "B")

    listed = await client.get(
        "/api/v1/inventory/material-subcategories",
        headers=headers,
        params={"company_id": company_a, "page_size": 50},
    )
    assert listed.status_code == 200, listed.text
    ids = {row["id"] for row in listed.json()["data"]}
    assert material_a in ids
    assert all(row["company_id"] == company_a for row in listed.json()["data"])


async def test_material_history_ledger(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    company_id = await _create_company(client, headers)
    mm_unit_id = await _unit_id_by_code(client, headers, "mm")

    product = await client.post(
        "/api/v1/inventory/material-categories",
        headers=headers,
        json={"name": f"Hist-{uuid4().hex[:6]}", "company_id": company_id},
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["data"]["id"]
    company_name = product.json()["data"]["company_name"]

    micron = await client.post(
        "/api/v1/inventory/microns",
        headers=headers,
        json={"product_id": product_id, "name": "12 MIC", "price_per_unit": "95"},
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
            "opening_rolls": "10",
            "opening_kg": "100",
        },
    )
    assert material.status_code == 201, material.text
    material_id = material.json()["data"]["id"]

    patch = await client.patch(
        f"/api/v1/inventory/material-subcategories/{material_id}",
        headers=headers,
        json={"rolls_on_hand": "15"},
    )
    assert patch.status_code == 200, patch.text

    history = await client.get(
        f"/api/v1/inventory/material-subcategories/{material_id}/history",
        headers=headers,
        params={"page_size": 50},
    )
    assert history.status_code == 200, history.text
    entries = history.json()["data"]
    assert all(row["kind"] == "stock" for row in entries)
    assert all(row["action"] in ("IN", "OUT", "OPENING") for row in entries)
    opening = next(row for row in entries if row["action"] == "OPENING")
    assert float(opening["rolls"]) == 10
    assert float(opening["kilograms"]) == 100
    roll_in = next(row for row in entries if row["action"] == "IN")
    assert float(roll_in["rolls"]) == 5
    assert roll_in["company_name"] == company_name
    assert float(roll_in["price_per_unit"]) == 95

    summary = await client.get(
        f"/api/v1/inventory/material-subcategories/{material_id}/history-summary",
        headers=headers,
    )
    assert summary.status_code == 200, summary.text
    body = summary.json()["data"]
    assert body["company_id"] == company_id
    assert float(body["last_purchase_rolls"]) == 5
    assert float(body["last_purchase_price"]) == 95


async def test_material_update_combines_roll_and_kg_movement(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    company_id = await _create_company(client, headers)
    mm_unit_id = await _unit_id_by_code(client, headers, "mm")

    product = await client.post(
        "/api/v1/inventory/material-categories",
        headers=headers,
        json={"name": f"Comb-{uuid4().hex[:6]}", "company_id": company_id},
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["data"]["id"]

    micron = await client.post(
        "/api/v1/inventory/microns",
        headers=headers,
        json={"product_id": product_id, "name": "25", "price_per_unit": "80"},
    )
    assert micron.status_code == 201, micron.text
    micron_id = micron.json()["data"]["id"]

    material = await client.post(
        "/api/v1/inventory/material-subcategories",
        headers=headers,
        json={
            "parent_id": micron_id,
            "size": "740",
            "size_unit_id": mm_unit_id,
            "opening_rolls": "10",
            "opening_kg": "2000",
        },
    )
    assert material.status_code == 201, material.text
    material_id = material.json()["data"]["id"]

    patch = await client.patch(
        f"/api/v1/inventory/material-subcategories/{material_id}",
        headers=headers,
        json={"rolls_on_hand": "8", "total_kg": "1660"},
    )
    assert patch.status_code == 200, patch.text

    history = await client.get(
        f"/api/v1/inventory/material-subcategories/{material_id}/history",
        headers=headers,
        params={"page_size": 50},
    )
    assert history.status_code == 200, history.text
    stock_out = [row for row in history.json()["data"] if row["action"] == "OUT"]
    assert len(stock_out) == 1
    assert float(stock_out[0]["rolls"]) == 2
    assert float(stock_out[0]["kilograms"]) == 340
    assert stock_out[0]["note"] == "Stock updated from material"
