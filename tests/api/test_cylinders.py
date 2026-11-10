"""Jobs and cylinder returns API tests."""

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


def _cylinder_payload(company_id: str) -> dict:
    return {
        "company_id": company_id,
        "product_name": "Test film",
        "cylinder_count": 2,
        "cylinders": [
            {"width": "10", "circumference": "20"},
            {"width": "11", "circumference": "21"},
        ],
        "color_count": 1,
        "colors": [{"name": "Red"}],
        "pet_size": "500ml",
        "cylinder_location": "Rack A",
        "remarks": "Note",
        "status": "ACTIVE",
    }


async def test_cylinders_crud_pause_return_and_files(client: AsyncClient) -> None:
    email, password = await provision_admin()
    headers = await login_headers(client, email, password)
    company_id = await _create_company(client, headers)

    missing_pet_size = dict(_cylinder_payload(company_id))
    missing_pet_size.pop("pet_size")
    rejected = await client.post(
        "/api/v1/inventory/cylinders",
        headers=headers,
        json=missing_pet_size,
    )
    assert rejected.status_code == 422, rejected.text

    create = await client.post(
        "/api/v1/inventory/cylinders",
        headers=headers,
        json=_cylinder_payload(company_id),
    )
    assert create.status_code == 201, create.text
    cylinder_id = create.json()["data"]["id"]
    assert create.json()["data"]["cylinder_count"] == 2

    listing = await client.get("/api/v1/inventory/cylinders", headers=headers)
    assert listing.status_code == 200
    assert any(row["id"] == cylinder_id for row in listing.json()["data"])

    pause = await client.post(
        f"/api/v1/inventory/cylinders/{cylinder_id}/pause",
        headers=headers,
        json={"pause_remarks": "Waiting material"},
    )
    assert pause.status_code == 200, pause.text
    assert pause.json()["data"]["status"] == "PAUSED"

    default_list_while_paused = await client.get("/api/v1/inventory/cylinders", headers=headers)
    assert all(row["id"] != cylinder_id for row in default_list_while_paused.json()["data"])

    paused_list = await client.get(
        "/api/v1/inventory/cylinders",
        headers=headers,
        params={"status": "PAUSED"},
    )
    assert any(row["id"] == cylinder_id for row in paused_list.json()["data"])

    pause_again = await client.post(
        f"/api/v1/inventory/cylinders/{cylinder_id}/pause",
        headers=headers,
        json={"pause_remarks": "Again"},
    )
    assert pause_again.status_code == 422

    resume = await client.post(
        f"/api/v1/inventory/cylinders/{cylinder_id}/resume",
        headers=headers,
        json={"resume_remarks": "Material arrived"},
    )
    assert resume.status_code == 200
    assert resume.json()["data"]["status"] == "ACTIVE"
    assert resume.json()["data"]["pauses"][0]["resume_remarks"] == "Material arrived"

    default_list_after_resume = await client.get("/api/v1/inventory/cylinders", headers=headers)
    assert any(row["id"] == cylinder_id for row in default_list_after_resume.json()["data"])

    complete_payload = _cylinder_payload(company_id)
    complete_payload["status"] = "COMPLETED"
    complete_payload["cylinder_cost"] = "245.00"
    updated = await client.patch(
        f"/api/v1/inventory/cylinders/{cylinder_id}",
        headers=headers,
        json=complete_payload,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["status"] == "COMPLETED"
    assert len(updated.json()["data"]["colors"]) == 1
    assert len(updated.json()["data"]["cylinders"]) == 2

    completed_list = await client.get("/api/v1/inventory/cylinders", headers=headers)
    assert any(row["id"] == cylinder_id for row in completed_list.json()["data"])

    history = await client.get(f"/api/v1/inventory/cylinders/{cylinder_id}/history", headers=headers)
    assert history.status_code == 200, history.text
    lifecycle = {
        row["event"]: row for row in history.json()["data"] if row["event"] in {"pause", "resume"}
    }
    assert set(lifecycle) == {"pause", "resume"}
    assert all(row["kind"] == "edit" and row["changes"] == [] for row in lifecycle.values())
    assert lifecycle["pause"]["summary"] == "Waiting material"
    assert lifecycle["resume"]["summary"] == "Material arrived"

    pdf_bytes = b"%PDF-1.4 test"
    upload = await client.post(
        f"/api/v1/inventory/cylinders/{cylinder_id}/files/cylinder_image",
        headers=headers,
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload.status_code == 200, upload.text

    listed = await client.get("/api/v1/inventory/cylinders", headers=headers)
    listed_row = next(row for row in listed.json()["data"] if row["id"] == cylinder_id)
    assert listed_row["cylinder_image"]["filename"] == "test.pdf"
    assert listed_row["cylinder_image"]["content_type"] == "application/pdf"

    download = await client.get(
        f"/api/v1/inventory/cylinders/{cylinder_id}/files/cylinder_image",
        headers=headers,
    )
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF")

    create_return = await client.post(
        "/api/v1/inventory/cylinder-returns",
        headers=headers,
        json={"cylinder_id": cylinder_id, "company_id": company_id, "remarks": "Returned all"},
    )
    assert create_return.status_code == 201, create_return.text
    return_id = create_return.json()["data"]["id"]
    return_detail = await client.get(f"/api/v1/inventory/cylinder-returns/{return_id}", headers=headers)
    assert return_detail.status_code == 200, return_detail.text
    return_data = return_detail.json()["data"]
    assert return_data["product_name"] == "Test film"
    assert return_data["cylinder_count"] == 2
    assert return_data["company_gst_number"] is None

    job_after = await client.get(f"/api/v1/inventory/cylinders/{cylinder_id}", headers=headers)
    assert job_after.json()["data"]["status"] == "RETURNED"

    closed_list = await client.get("/api/v1/inventory/cylinders", headers=headers)
    assert all(row["id"] != cylinder_id for row in closed_list.json()["data"])

    open_with_closed = await client.get(
        "/api/v1/inventory/cylinders",
        headers=headers,
        params={"include_closed": True, "status": "RETURNED"},
    )
    assert any(row["id"] == cylinder_id for row in open_with_closed.json()["data"])
