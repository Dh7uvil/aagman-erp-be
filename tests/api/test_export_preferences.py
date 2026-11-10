"""Export column preferences API."""

from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def test_export_preference_save_and_reset(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)

    get_default = await client.get(
        "/api/v1/users/me/table-preferences/inventory.materials",
        headers=headers,
    )
    assert get_default.status_code == 200
    data = get_default.json()["data"]
    assert "export_visible_columns" in data
    assert data["export_is_default"] is True

    save = await client.put(
        "/api/v1/users/me/table-preferences/inventory.materials/export",
        headers=headers,
        json={
            "export_visible_columns": ["product", "rolls", "total_kg"],
            "export_column_order": ["product", "rolls", "total_kg"],
            "export_format": "xlsx",
        },
    )
    assert save.status_code == 200
    saved = save.json()["data"]
    assert saved["export_is_default"] is False
    assert saved["export_format"] == "xlsx"
    assert saved["visible_columns"]  # list prefs unchanged defaults

    reset = await client.delete(
        "/api/v1/users/me/table-preferences/inventory.materials/export",
        headers=headers,
    )
    assert reset.status_code == 200
    assert reset.json()["data"]["export_is_default"] is True
