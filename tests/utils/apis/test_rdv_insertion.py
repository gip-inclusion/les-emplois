import httpx
import pytest
from django.core.exceptions import ImproperlyConfigured

from itou.utils.apis import rdv_insertion


SEARCH_URL = "https://rdv-insertion.fake/api/plateforme_inclusion/users/search"
NIR = "285032612345653"


@pytest.fixture
def rdvi_settings(settings):
    settings.RDV_INSERTION_PLATEFORME_INCLUSION_API_BASE_URL = "https://rdv-insertion.fake/api/plateforme_inclusion/"
    settings.RDV_INSERTION_PLATEFORME_INCLUSION_API_TOKEN = "S3cr3t!"
    return settings


def test_improperly_configured(rdvi_settings):
    rdvi_settings.RDV_INSERTION_PLATEFORME_INCLUSION_API_TOKEN = ""
    with pytest.raises(ImproperlyConfigured):
        rdv_insertion.get_client()


def test_search_user_by_nir(respx_mock, rdvi_settings):
    respx_mock.post(SEARCH_URL, json={"nir": NIR}, headers={"Authorization": "Bearer S3cr3t!"}).respond(
        200, json={"user": {"id": 1, "follow_ups": []}}
    )
    assert rdv_insertion.get_client().search_user_by_nir(NIR) == {"id": 1, "follow_ups": []}


@pytest.mark.parametrize(
    "status_code, error",
    [
        (404, "Aucun usager ne correspond à ce NIR"),
        (409, "Plusieurs usagers correspondent à ce NIR"),
    ],
)
def test_search_user_by_nir_not_found_or_several(respx_mock, rdvi_settings, status_code, error):
    respx_mock.post(SEARCH_URL).respond(status_code, json={"errors": [error]})
    assert rdv_insertion.get_client().search_user_by_nir(NIR) is None


def test_search_user_by_nir_errors(respx_mock, rdvi_settings):
    client = rdv_insertion.get_client()

    respx_mock.post(SEARCH_URL).mock(side_effect=httpx.ReadTimeout)
    with pytest.raises(rdv_insertion.RdvInsertionApiError, match="ReadTimeout"):
        client.search_user_by_nir(NIR)

    respx_mock.post(SEARCH_URL).respond(500)
    with pytest.raises(rdv_insertion.RdvInsertionApiError, match="HTTPStatusError"):
        client.search_user_by_nir(NIR)

    respx_mock.post(SEARCH_URL).respond(200, content="not json")
    with pytest.raises(rdv_insertion.RdvInsertionApiError, match="JSONDecodeError"):
        client.search_user_by_nir(NIR)
