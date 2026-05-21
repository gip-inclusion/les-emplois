import io

import httpx
import pytest
import respx

from itou.utils.apis.dora import DoraAPIClient, DoraAPIException


DORA_BASE_URL = "https://dora-api.example.com"


@pytest.fixture
def dora_client():
    return DoraAPIClient(DORA_BASE_URL, "token")


def test_reference_data(dora_client):
    with respx.mock(base_url=f"{DORA_BASE_URL}/api/emplois/") as respx_mock:
        route = respx_mock.get("/reference-data/").respond(200, json={"foo": "bar"})
        response = dora_client.reference_data(page=1)

    assert response == {"foo": "bar"}
    assert route.called


def test_safe_upload_posts_to_root_safe_upload_url(dora_client):
    with respx.mock() as respx_mock:
        route = respx_mock.post(f"{DORA_BASE_URL}/safe-upload/doc%20name.pdf/").respond(
            201,
            json={"key": "local/#orientations/abc/doc name.pdf"},
        )
        response = dora_client.safe_upload("doc name.pdf", io.BytesIO(b"file-content"))

    assert response == {"key": "local/#orientations/abc/doc name.pdf"}
    assert route.called


def test_safe_upload_raises_on_http_error(dora_client):
    with respx.mock() as respx_mock:
        respx_mock.post(f"{DORA_BASE_URL}/safe-upload/doc.pdf/").respond(500)
        with pytest.raises(DoraAPIException):
            dora_client.safe_upload("doc.pdf", io.BytesIO(b"file-content"))


def test_create_orientation_posts_to_api_emplois_orientations(dora_client):
    payload = {"di_service_id": "soliguide--svc-1", "beneficiary_email": "boris@example.org"}

    with respx.mock(base_url=f"{DORA_BASE_URL}/api/emplois/") as respx_mock:
        route = respx_mock.post("/orientations/").respond(201, json={"id": "orientation-1"})
        response = dora_client.create_orientation(payload)

    assert response == {"id": "orientation-1"}
    assert route.called
    assert route.calls.last.request.content.decode() == httpx.Request("POST", "", json=payload).content.decode()


def test_create_orientation_raises_on_http_error(dora_client):
    with respx.mock(base_url=f"{DORA_BASE_URL}/api/emplois/") as respx_mock:
        respx_mock.post("/orientations/").respond(500)
        with pytest.raises(DoraAPIException):
            dora_client.create_orientation({"di_service_id": "soliguide--svc-1"})
