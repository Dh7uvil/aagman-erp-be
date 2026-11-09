"""Solvent inventory API tests."""

from datetime import date
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _create_company(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/companies",
        headers=headers,
        json={"name": f"SolventCo-{uuid4().hex[:8]}"},
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


async def _create_name(client: AsyncClient, headers: dict[str, str], code: str) -> str:
    response = await client.post(
        "/api/v1/inventory/solvent-names",
        headers=headers,
        json={"name": code},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


async def _create_brand(client: AsyncClient, headers: dict[str, str], name: str) -> str:
    response = await client.post(
        "/api/v1/inventory/solvent-brands",
        headers=headers,
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


async def test_solvent_code_validation_and_duplicate(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)

    name = f"ADH-{uuid4().hex[:6]}"
    created = await client.post(
        "/api/v1/inventory/solvent-names",
        headers=headers,
        json={"name": name},
    )
    assert created.status_code == 201

    dup = await client.post(
        "/api/v1/inventory/solvent-names",
        headers=headers,
        json={"name": name},
    )
    assert dup.status_code == 409


async def test_solvent_sheet_one_per_company_and_line_totals(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    kg_unit = await _unit_id_by_code(client, headers, "kg")
    company_id = await _create_company(client, headers)
    brand_id = await _create_brand(client, headers, f"Brand-{uuid4().hex[:4]}")
    code_a = await _create_name(client, headers, f"CodeA-{uuid4().hex[:4]}")
    code_b = await _create_name(client, headers, f"CodeB-{uuid4().hex[:4]}")

    create = await client.post(
        "/api/v1/inventory/solvents",
        headers=headers,
        json={
            "company_id": company_id,
            "lines": [
                {
                    "brand_id": brand_id,
                    "solvent_name_id": code_a,
                    "drum_count": "2",
                    "drum_qty": "25",
                    "drum_unit_id": kg_unit,
                    "solvent_rate": "10",
                },
                {
                    "brand_id": brand_id,
                    "solvent_name_id": code_b,
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
    by_code = {row["solvent_name_id"]: row for row in lines}
    assert float(by_code[code_a]["total_qty"]) == 50
    assert float(by_code[code_a]["total_rate"]) == 500
    assert float(by_code[code_b]["total_qty"]) == 20

    add_stock = await client.post(
        "/api/v1/inventory/solvents",
        headers=headers,
        json={
            "company_id": company_id,
            "lines": [
                {
                    "brand_id": brand_id,
                    "solvent_name_id": code_a,
                    "drum_count": "1",
                    "drum_qty": "25",
                    "drum_unit_id": kg_unit,
                    "solvent_rate": "12",
                },
            ],
        },
    )
    assert add_stock.status_code == 201, add_stock.text
    assert add_stock.json()["data"]["id"] == sheet_id
    merged_lines = add_stock.json()["data"]["lines"]
    merged_a = next(row for row in merged_lines if row["solvent_name_id"] == code_a)
    assert float(merged_a["drum_count"]) == 3
    assert float(merged_a["total_qty"]) == 75

    history = await client.get(
        f"/api/v1/inventory/solvent-lines/{merged_a['id']}/history",
        headers=headers,
    )
    assert history.status_code == 200, history.text
    assert any(row["action"] == "IN" for row in history.json()["data"])

    summary = await client.get(
        f"/api/v1/inventory/solvent-lines/{merged_a['id']}/history-summary",
        headers=headers,
    )
    assert summary.status_code == 200, summary.text
    avg = float(summary.json()["data"]["avg_price_per_unit"])
    assert avg == pytest.approx(10.67)

    sheet = await client.get(f"/api/v1/inventory/solvents/{sheet_id}", headers=headers)
    assert sheet.status_code == 200, sheet.text
    line_a = next(row for row in sheet.json()["data"]["lines"] if row["solvent_name_id"] == code_a)
    assert float(line_a["avg_price_per_unit"]) == pytest.approx(10.67)


async def test_solvent_sheet_update_removes_one_line(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    kg_unit = await _unit_id_by_code(client, headers, "kg")
    company_id = await _create_company(client, headers)
    brand_id = await _create_brand(client, headers, f"Brand-{uuid4().hex[:4]}")
    code_a = await _create_name(client, headers, f"Keep-{uuid4().hex[:4]}")
    code_b = await _create_name(client, headers, f"Drop-{uuid4().hex[:4]}")

    create = await client.post(
        "/api/v1/inventory/solvents",
        headers=headers,
        json={
            "company_id": company_id,
            "lines": [
                {
                    "brand_id": brand_id,
                    "solvent_name_id": code_a,
                    "drum_count": "0",
                    "drum_qty": "0",
                    "drum_unit_id": kg_unit,
                },
                {
                    "brand_id": brand_id,
                    "solvent_name_id": code_b,
                    "drum_count": "0",
                    "drum_qty": "0",
                    "drum_unit_id": kg_unit,
                },
            ],
        },
    )
    assert create.status_code == 201, create.text
    sheet_id = create.json()["data"]["id"]
    lines = create.json()["data"]["lines"]
    assert len(lines) == 2
    keep = next(row for row in lines if row["solvent_name_id"] == code_a)

    updated = await client.patch(
        f"/api/v1/inventory/solvents/{sheet_id}",
        headers=headers,
        json={
            "lines": [
                {
                    "id": keep["id"],
                    "brand_id": brand_id,
                    "solvent_name_id": code_a,
                    "drum_count": "0",
                    "drum_qty": "0",
                    "drum_unit_id": kg_unit,
                },
            ]
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()["data"]
    assert len(body["lines"]) == 1
    assert body["lines"][0]["id"] == keep["id"]
    assert body["lines"][0]["solvent_name_id"] == code_a


async def test_solvent_stock_out_and_code_usage(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    kg_unit = await _unit_id_by_code(client, headers, "kg")
    company_id = await _create_company(client, headers)
    brand_id = await _create_brand(client, headers, f"Brand-{uuid4().hex[:4]}")
    solvent_name_id = await _create_name(client, headers, f"Usage-{uuid4().hex[:4]}")

    create = await client.post(
        "/api/v1/inventory/solvents",
        headers=headers,
        json={
            "company_id": company_id,
            "lines": [
                {
                    "brand_id": brand_id,
                    "solvent_name_id": solvent_name_id,
                    "drum_count": "4",
                    "drum_qty": "10",
                    "drum_unit_id": kg_unit,
                    "solvent_rate": "5",
                }
            ],
        },
    )
    assert create.status_code == 201, create.text
    sheet_id = create.json()["data"]["id"]
    line_id = create.json()["data"]["lines"][0]["id"]

    over = await client.post(
        f"/api/v1/inventory/solvents/{sheet_id}/stock-out",
        headers=headers,
        json={"solvent_line_id": line_id, "drums": "5", "quantity": "0"},
    )
    assert over.status_code == 409

    out = await client.post(
        f"/api/v1/inventory/solvents/{sheet_id}/stock-out",
        headers=headers,
        json={"solvent_line_id": line_id, "drums": "1", "quantity": "5"},
    )
    assert out.status_code == 200, out.text
    assert float(out.json()["data"]["drum_count"]) == 3
    assert float(out.json()["data"]["total_qty"]) == 35

    usage = await client.get(f"/api/v1/inventory/solvent-names/{solvent_name_id}/usage", headers=headers)
    assert usage.status_code == 200
    body = usage.json()["data"]
    assert body["companies_with_stock"] == 1
    assert len(body["lines"]) == 1
    assert body["lines"][0]["company_id"] == company_id

    history = await client.get(
        f"/api/v1/inventory/solvent-lines/{line_id}/history",
        headers=headers,
    )
    assert history.status_code == 200, history.text
    stock_rows = history.json()["data"]
    assert any(row["action"] == "OPENING" for row in stock_rows)
    assert any(row["action"] == "OUT" for row in stock_rows)

    summary = await client.get(
        f"/api/v1/inventory/solvent-lines/{line_id}/history-summary",
        headers=headers,
    )
    assert summary.status_code == 200, summary.text
    assert float(summary.json()["data"]["drums_on_hand"]) == 3
    assert float(summary.json()["data"]["total_qty"]) == 35


async def test_solvent_movement_day_report(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    kg_unit = await _unit_id_by_code(client, headers, "kg")
    company_id = await _create_company(client, headers)
    brand_id = await _create_brand(client, headers, f"Brand-{uuid4().hex[:4]}")
    solvent_name_id = await _create_name(client, headers, f"Move-{uuid4().hex[:4]}")

    create = await client.post(
        "/api/v1/inventory/solvents",
        headers=headers,
        json={
            "company_id": company_id,
            "lines": [
                {
                    "brand_id": brand_id,
                    "solvent_name_id": solvent_name_id,
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
        f"/api/v1/inventory/solvents/{sheet_id}/stock-out",
        headers=headers,
        json={"solvent_line_id": line_id, "drums": "1", "quantity": "10", "movement_date": today},
    )

    report = await client.get(
        "/api/v1/inventory/solvent-movements/report",
        headers=headers,
        params={"date": today},
    )
    assert report.status_code == 200
    rows = report.json()["data"]
    match = [row for row in rows if row["solvent_line_id"] == line_id]
    assert len(match) == 1
    assert float(match[0]["out_drums"]) == 1
    assert float(match[0]["out_qty"]) == 10
    assert float(match[0]["closing_drums"]) == 1
    assert float(match[0]["closing_qty"]) == 10


async def test_solvent_movement_day_report_counts_opening_as_in(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    kg_unit = await _unit_id_by_code(client, headers, "kg")
    company_id = await _create_company(client, headers)
    brand_id = await _create_brand(client, headers, f"Brand-{uuid4().hex[:4]}")
    solvent_name_id = await _create_name(client, headers, f"Open-{uuid4().hex[:4]}")

    create = await client.post(
        "/api/v1/inventory/solvents",
        headers=headers,
        json={
            "company_id": company_id,
            "lines": [
                {
                    "brand_id": brand_id,
                    "solvent_name_id": solvent_name_id,
                    "drum_count": "2",
                    "drum_qty": "10",
                    "drum_unit_id": kg_unit,
                }
            ],
        },
    )
    assert create.status_code == 201, create.text
    line_id = create.json()["data"]["lines"][0]["id"]
    today = date.today().isoformat()

    report = await client.get(
        "/api/v1/inventory/solvent-movements/report",
        headers=headers,
        params={"start_date": today, "end_date": today},
    )
    assert report.status_code == 200, report.text
    match = [row for row in report.json()["data"] if row["solvent_line_id"] == line_id]
    assert len(match) == 1
    assert float(match[0]["in_drums"]) == 2
    assert float(match[0]["in_qty"]) == 20
    assert float(match[0]["closing_drums"]) == 2
    assert float(match[0]["closing_qty"]) == 20


async def test_solvent_code_usage_table_preference_matches_sheet_columns(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    response = await client.put(
        "/api/v1/users/me/table-preferences/inventory.solvent_name_usage",
        headers=headers,
        json={
            "visible_columns": ["company", "brand", "drum_count", "total_qty", "avg_price_per_unit"],
            "column_order": [
                "company",
                "brand",
                "drum_count",
                "drum_qty",
                "unit",
                "total_qty",
                "solvent_rate",
                "avg_price_per_unit",
                "total_rate",
                "sheet",
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert "avg_price_per_unit" in body["column_order"]


async def test_solvents_table_preference_accepts_code_and_avg_rate_columns(
    client: AsyncClient,
) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    response = await client.put(
        "/api/v1/users/me/table-preferences/inventory.solvents",
        headers=headers,
        json={
            "visible_columns": ["company", "brand", "name", "total_qty", "avg_price_per_unit"],
            "column_order": [
                "company",
                "brand",
                "name",
                "drum_count",
                "total_qty",
                "solvent_rate",
                "avg_price_per_unit",
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert "name" in body["column_order"]
    assert "avg_price_per_unit" in body["column_order"]

    rejected = await client.put(
        "/api/v1/users/me/table-preferences/inventory.solvents",
        headers=headers,
        json={
            "visible_columns": ["company", "color"],
            "column_order": ["company", "color"],
        },
    )
    assert rejected.status_code == 422


async def test_solvents_dashboard_no_dead_stock(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    res = await client.get("/api/v1/inventory/dashboard/solvents", headers=headers)
    assert res.status_code == 200
    body = res.json()["data"]
    assert "dead_stock" not in body
    assert "dead_stock_lines" not in body.get("kpis", {})
