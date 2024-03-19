import pytest
from django.contrib.gis.geos import GEOSGeometry

from itou.utils.apis import geocoding
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_NO_RESULT_MOCK, BAN_GEOCODING_API_WITH_RESULT_RESPONSE


def test_get_geocoding_data(caplog, snapshot, respx_mock, settings):
    settings.API_BAN_BASE_URL = "https://geo.foo"
    respx_mock.get(f"{settings.API_BAN_BASE_URL}/search/").respond(200, json=BAN_GEOCODING_API_WITH_RESULT_RESPONSE)

    result = geocoding.get_geocoding_data("")
    # Expected data comes from BAN_GEOCODING_API_RESULT_MOCK.
    assert result == {
        "score": 0.5197687103594081,
        "address_line_1": "10 Place des Cinq Martyrs du Lycée Buffon",
        "number": "10",
        "lane": "Place des Cinq Martyrs du Lycée Buffon",
        "address": "10 Place des Cinq Martyrs du Lycée Buffon",
        "post_code": "75015",
        "insee_code": "75115",
        "city": "Paris",
        "longitude": 2.316754,
        "latitude": 48.838411,
        "coords": GEOSGeometry("POINT(2.316754 48.838411)"),
    }
    assert [record for record in caplog.record_tuples if record[0] == geocoding.__name__] == snapshot


def test_get_geocoding_data_error(caplog, snapshot, respx_mock, settings):
    settings.API_BAN_BASE_URL = "https://geo.foo"
    respx_mock.get(f"{settings.API_BAN_BASE_URL}/search/").respond(200, json=BAN_GEOCODING_API_NO_RESULT_MOCK)

    with pytest.raises(GeocodingDataError):
        geocoding.get_geocoding_data("")
    assert [record for record in caplog.record_tuples if record[0] == geocoding.__name__] == snapshot


@pytest.mark.parametrize("post_code", ["97000", "98999"])
def test_get_geocoding_data_try_without_post_code_if_no_results_for_drom_and_com(
    caplog, snapshot, respx_mock, settings, post_code
):
    settings.API_BAN_BASE_URL = "https://geo.foo"
    respx_mock.get(f"{settings.API_BAN_BASE_URL}/search/").respond(200, json=BAN_GEOCODING_API_NO_RESULT_MOCK)

    with pytest.raises(GeocodingDataError):
        geocoding.get_geocoding_data("HOWELL CENTER", post_code=post_code)
    assert [record for record in caplog.record_tuples if record[0] == geocoding.__name__] == snapshot
