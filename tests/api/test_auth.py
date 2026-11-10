"""Authentication API tests."""

from httpx import AsyncClient

from tests.conftest import ADMIN_PASSWORD, login_headers, provision_admin


async def test_login_and_me(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)

    me_response = await client.get("/api/v1/auth/me", headers=headers)
    assert me_response.status_code == 200, me_response.text
    body = me_response.json()["data"]
    assert body["email"] == email
    assert "identity.user.read" in body["permissions"]


async def test_login_invalid_password(client: AsyncClient) -> None:
    email, _ = await provision_admin()
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WrongPassword1"},
    )
    assert response.status_code == 401
