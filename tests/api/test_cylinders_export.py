"""Cylinder list export columns."""

from httpx import AsyncClient

from tests.api.test_cylinders import _create_company, _cylinder_payload
from tests.conftest import login_headers, provision_admin


async def test_cylinder_export_includes_cost_columns(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    company_id = await _create_company(client, headers)

    create = await client.post(
        "/api/v1/inventory/cylinders",
        headers=headers,
        json=_cylinder_payload(company_id),
    )
    assert create.status_code == 201, create.text
    cylinder_id = create.json()["data"]["id"]

    updated = await client.patch(
        f"/api/v1/inventory/cylinders/{cylinder_id}",
        headers=headers,
        json={**_cylinder_payload(company_id), "status": "COMPLETED", "cylinder_cost": "100"},
    )
    assert updated.status_code == 200, updated.text

    await client.put(
        "/api/v1/users/me/table-preferences/inventory.cylinders/export",
        headers=headers,
        json={
            "export_visible_columns": [
                "cylinder_number",
                "cylinder_cost",
                "total_cylinder_cost",
            ],
            "export_column_order": [
                "cylinder_number",
                "cylinder_cost",
                "total_cylinder_cost",
                "cylinder_count",
            ],
            "export_format": "csv",
        },
    )

    response = await client.get(
        "/api/v1/inventory/cylinders/export",
        headers=headers,
        params={"format": "csv", "export_scope": "all", "include_closed": "true"},
    )
    assert response.status_code == 200, response.text
    lines = response.text.strip().splitlines()
    assert lines[0] == "Cylinder #,Cylinder cost,Total cylinder cost"
    data_row = next(line for line in lines[1:] if line and not line.startswith("Total"))
    assert ",100,200" in data_row or data_row.endswith(",100,200")
    totals = lines[-1]
    assert totals.startswith("Total,")
    assert totals.endswith(",200")
    assert ",100," in totals or totals.split(",")[1] == "100"


async def test_export_falls_back_to_list_visible_columns(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)

    await client.put(
        "/api/v1/users/me/table-preferences/inventory.cylinders",
        headers=headers,
        json={
            "visible_columns": [
                "cylinder_number",
                "cylinder_cost",
                "total_cylinder_cost",
            ],
            "column_order": [
                "cylinder_number",
                "company",
                "product",
                "status",
                "cylinder_count",
                "cylinder_cost",
                "total_cylinder_cost",
            ],
        },
    )

    prefs = await client.get(
        "/api/v1/users/me/table-preferences/inventory.cylinders",
        headers=headers,
    )
    assert prefs.status_code == 200
    body = prefs.json()["data"]
    assert "cylinder_cost" in body["export_visible_columns"]
    assert "total_cylinder_cost" in body["export_visible_columns"]
