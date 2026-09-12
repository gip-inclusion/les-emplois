import pytest
import respx

from itou.utils.apis.dora import DoraAPIClient


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
