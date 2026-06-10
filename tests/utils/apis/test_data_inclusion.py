import pytest

from itou.utils import constants as global_constants
from itou.utils.apis.data_inclusion import DataInclusionApiClient


BASE_URL = global_constants.API_DATA_INCLUSION_BASE_URL
SEARCH_URL = BASE_URL + "/api/v1/search/services"


@pytest.mark.parametrize(
    "reseaux_porteurs,expected",
    [
        (["plie"], True),
        (["epide"], True),
        ([], False),
        (None, False),  # reseaux_porteurs can be null in the API response
    ],
)
# tests the client-side filtering on the SPS networks
def test_search_sps_services_filter(respx_mock, reseaux_porteurs, expected):
    structure = {"reseaux_porteurs": reseaux_porteurs}
    respx_mock.get(SEARCH_URL).respond(200, json={"items": [{"service": {"id": "s1", "structure": structure}}]})
    results = DataInclusionApiClient(BASE_URL, "test-token").search_sps_services(code_commune="59350")
    assert (len(results) == 1) == expected
