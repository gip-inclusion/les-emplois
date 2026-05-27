import io
import json

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


def test_create_orientation_posts_multipart_with_attachments(dora_client):
    payload = {"di_service_id": "soliguide--svc-1", "beneficiary_email": "boris@example.org"}

    with respx.mock(base_url=f"{DORA_BASE_URL}/api/emplois/") as respx_mock:
        route = respx_mock.post("/orientations/").respond(201, json={"id": "orientation-1"})
        response = dora_client.create_orientation(payload, [("doc.pdf", io.BytesIO(b"file-content"))])

    assert response == {"id": "orientation-1"}
    assert route.called
    request = route.calls.last.request
    assert request.headers["content-type"].startswith("multipart/form-data")
    body = request.content
    assert b'name="data"' in body
    assert json.dumps(payload).encode() in body
    assert b'name="attachments"; filename="doc.pdf"' in body
    assert b"file-content" in body


def test_create_orientation_without_attachments_sends_data_only(dora_client):
    payload = {"di_service_id": "soliguide--svc-1"}

    with respx.mock(base_url=f"{DORA_BASE_URL}/api/emplois/") as respx_mock:
        route = respx_mock.post("/orientations/").respond(201, json={"id": "orientation-1"})
        response = dora_client.create_orientation(payload)

    assert response == {"id": "orientation-1"}
    assert b"di_service_id" in route.calls.last.request.content


def test_create_orientation_raises_on_http_error(dora_client):
    with respx.mock(base_url=f"{DORA_BASE_URL}/api/emplois/") as respx_mock:
        respx_mock.post("/orientations/").respond(500)
        with pytest.raises(DoraAPIException) as exc_info:
            dora_client.create_orientation({"di_service_id": "soliguide--svc-1"})

    assert exc_info.value.validation_errors is None
    assert exc_info.value.status_code == 500


def test_create_orientation_raises_with_validation_errors_on_bad_request(dora_client):
    validation_errors = {
        "emplois_data": {
            "structure_siret": ["Ce champ est obligatoire."],
            "prescriber_phone": ["Ce champ est obligatoire."],
        }
    }

    with respx.mock(base_url=f"{DORA_BASE_URL}/api/emplois/") as respx_mock:
        respx_mock.post("/orientations/").respond(400, json=validation_errors)
        with pytest.raises(DoraAPIException) as exc_info:
            dora_client.create_orientation({"di_service_id": "soliguide--svc-1"})

    assert exc_info.value.validation_errors == validation_errors
    assert exc_info.value.status_code == 400
