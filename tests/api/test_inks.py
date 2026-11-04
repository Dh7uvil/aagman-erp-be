"""Ink inventory API tests."""

from datetime import date, timedelta
from uuid import uuid4

from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _create_company(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/companies",
        headers=headers,
        json={"name": f"InkCo-{uuid4().hex[:8]}"},
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


async def _create_color(client: AsyncClient, headers: dict[str, str], name: str, hex_code: str | None = None) -> str:
    payload: dict[str, object] = {"name": name}
    if hex_code is not None:
        payload["hex_code"] = hex_code
    response = await client.post("/api/v1/inventory/ink-colors", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


async def _create_brand(client: AsyncClient, headers: dict[str, str], name: str) -> str:
    response = await client.post(
        "/api/v1/inventory/ink-brands",
        headers=headers,
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


async def test_ink_color_validation_and_duplicate(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)

    bad_hex = await client.post(
        "/api/v1/inventory/ink-colors",
        headers=headers,
        json={"name": f"Red-{uuid4().hex[:4]}", "hex_code": "not-hex"},
    )
    assert bad_hex.status_code == 422

    name = f"Cyan-{uuid4().hex[:6]}"
    created = await client.post(
        "/api/v1/inventory/ink-colors",
        headers=headers,
        json={"name": name, "hex_code": "#aabbcc"},
    )
    assert created.status_code == 201
    assert created.json()["data"]["hex_code"] == "#AABBCC"

    dup = await client.post(
        "/api/v1/inventory/ink-colors",
        headers=headers,
        json={"name": name},
    )
    assert dup.status_code == 409


async def test_ink_sheet_one_per_company_and_line_totals(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    kg_unit = await _unit_id_by_code(client, headers, "kg")
    company_id = await _create_company(client, headers)
    brand_id = await _create_brand(client, headers, f"Brand-{uuid4().hex[:4]}")
    color_a = await _create_color(client, headers, f"ColorA-{uuid4().hex[:4]}", "#111111")
    color_b = await _create_color(client, headers, f"ColorB-{uuid4().hex[:4]}")

    create = await client.post(
        "/api/v1/inventory/inks",
        headers=headers,
        json={
            "company_id": company_id,
            "lines": [
                {
                    "brand_id": brand_id,
                    "color_id": color_a,
                    "drum_count": "2",
                    "drum_qty": "25",
                    "drum_unit_id": kg_unit,
                    "ink_rate": "10",
                },
                {
                    "brand_id": brand_id,
                    "color_id": color_b,
                    "drum_count": "1",
                    "drum_qty": "20",
                    "drum_unit_id": kg_unit,
                },
            ],
        },
    )
    assert create.status_code == 201, create.text
    sheet_id = create.json()["data"]["id"]
    lines = create.json()["data"]["lines"]
    assert len(lines) == 2
    by_color = {row["color_id"]: row for row in lines}
    assert float(by_color[color_a]["total_qty"]) == 50
    assert float(by_color[color_a]["total_rate"]) == 500
    assert float(by_color[color_b]["total_qty"]) == 20

    dup_sheet = await client.post(
        "/api/v1/inventory/inks",
        headers=headers,
        json={"company_id": company_id, "lines": []},
    )
    assert dup_sheet.status_code == 409

    dup_line = await client.patch(
        f"/api/v1/inventory/inks/{sheet_id}",
        headers=headers,
        json={
            "lines": [
                {
                    "id": by_color[color_a]["id"],
                    "brand_id": brand_id,
                    "color_id": color_a,
                    "drum_count": "2",
                    "drum_qty": "25",
                    "drum_unit_id": kg_unit,
                },
                {
                    "brand_id": brand_id,
                    "color_id": color_b,
                    "drum_count": "1",
                    "drum_qty": "20",
                    "drum_unit_id": kg_unit,
                },
            ]
        },
    )
    assert dup_line.status_code == 409


async def test_ink_stock_out_and_color_usage(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    kg_unit = await _unit_id_by_code(client, headers, "kg")
    company_id = await _create_company(client, headers)
    brand_id = await _create_brand(client, headers, f"Brand-{uuid4().hex[:4]}")
    color_id = await _create_color(client, headers, f"Usage-{uuid4().hex[:4]}", "#FF0000")

    create = await client.post(
        "/api/v1/inventory/inks",
        headers=headers,
        json={
            "company_id": company_id,
            "lines": [
                {
                    "brand_id": brand_id,
                    "color_id": color_id,
                    "drum_count": "4",
                    "drum_qty": "10",
                    "drum_unit_id": kg_unit,
                    "ink_rate": "5",
                }
            ],
        },
    )
    assert create.status_code == 201, create.text
    sheet_id = create.json()["data"]["id"]
    line_id = create.json()["data"]["lines"][0]["id"]

    over = await client.post(
        f"/api/v1/inventory/inks/{sheet_id}/stock-out",
        headers=headers,
        json={"ink_line_id": line_id, "drums": "5", "quantity": "0"},
    )
    assert over.status_code == 409

    out = await client.post(
        f"/api/v1/inventory/inks/{sheet_id}/stock-out",
        headers=headers,
        json={"ink_line_id": line_id, "drums": "1", "quantity": "5"},
    )
    assert out.status_code == 200, out.text
    assert float(out.json()["data"]["drum_count"]) == 3
    assert float(out.json()["data"]["total_qty"]) == 35

    usage = await client.get(f"/api/v1/inventory/ink-colors/{color_id}/usage", headers=headers)
    assert usage.status_code == 200
    body = usage.json()["data"]
    assert body["companies_with_stock"] == 1
    assert len(body["lines"]) == 1
    assert body["lines"][0]["company_id"] == company_id


async def test_ink_movement_day_report(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    kg_unit = await _unit_id_by_code(client, headers, "kg")
    company_id = await _create_company(client, headers)
    brand_id = await _create_brand(client, headers, f"Brand-{uuid4().hex[:4]}")
    color_id = await _create_color(client, headers, f"Move-{uuid4().hex[:4]}")

    create = await client.post(
        "/api/v1/inventory/inks",
        headers=headers,
        json={
            "company_id": company_id,
            "lines": [
                {
                    "brand_id": brand_id,
                    "color_id": color_id,
                    "drum_count": "2",
                    "drum_qty": "10",
                    "drum_unit_id": kg_unit,
                }
            ],
        },
    )
    assert create.status_code == 201
    sheet_id = create.json()["data"]["id"]
    line_id = create.json()["data"]["lines"][0]["id"]
    today = date.today().isoformat()

    await client.post(
        f"/api/v1/inventory/inks/{sheet_id}/stock-out",
        headers=headers,
        json={"ink_line_id": line_id, "drums": "1", "quantity": "10", "movement_date": today},
    )

    report = await client.get(
        "/api/v1/inventory/ink-movements/report",
        headers=headers,
        params={"date": today},
    )
    assert report.status_code == 200
    rows = report.json()["data"]
    match = [row for row in rows if row["ink_line_id"] == line_id]
    assert len(match) == 1
    assert float(match[0]["out_drums"]) == 1
    assert float(match[0]["out_qty"]) == 10
    assert float(match[0]["closing_drums"]) == 1
    assert float(match[0]["closing_qty"]) == 10


async def test_inks_dashboard_dead_stock_threshold(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)

    materials = await client.get(
        "/api/v1/inventory/dashboard/materials",
        headers=headers,
    )
    assert materials.status_code == 200

    inks = await client.get("/api/v1/inventory/dashboard/inks", headers=headers)
    assert inks.status_code == 200
    assert "dead_stock" in inks.json()["data"]
