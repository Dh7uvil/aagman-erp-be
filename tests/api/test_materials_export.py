"""Materials list export and column totals."""

from httpx import AsyncClient

from tests.api.test_inventory import _seed_product_micron_sku
from tests.conftest import login_headers, provision_admin


async def test_materials_export_csv(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    await _seed_product_micron_sku(client, headers)

    response = await client.get(
        "/api/v1/inventory/material-subcategories/export",
        headers=headers,
        params={"format": "csv"},
    )
    assert response.status_code == 200
    assert "text/csv" in response.headers.get("content-type", "")
    body = response.text
    assert "Total" in body.splitlines()[-1]


async def test_materials_list_column_totals_opt_in(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    await _seed_product_micron_sku(client, headers)

    without = await client.get(
        "/api/v1/inventory/material-subcategories",
        headers=headers,
    )
    assert "column_totals" not in (without.json().get("meta") or {})

    with_totals = await client.get(
        "/api/v1/inventory/material-subcategories",
        headers=headers,
        params={"include_column_totals": "true"},
    )
    meta = with_totals.json().get("meta") or {}
    assert "column_totals" in meta
    assert meta["column_totals"].get("rolls")


async def test_materials_export_all_scope_ignores_search(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    await _seed_product_micron_sku(client, headers)

    filtered = await client.get(
        "/api/v1/inventory/material-subcategories/export",
        headers=headers,
        params={"format": "csv", "export_scope": "filtered", "search": "no-match-xyz"},
    )
    assert filtered.status_code == 200
    assert filtered.text.count("\n") <= 2  # header + maybe totals only

    all_rows = await client.get(
        "/api/v1/inventory/material-subcategories/export",
        headers=headers,
        params={"format": "csv", "export_scope": "all", "search": "no-match-xyz"},
    )
    assert all_rows.status_code == 200
    assert all_rows.text.count("\n") > 2
