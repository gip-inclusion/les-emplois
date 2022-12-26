from unittest import mock

import pytest
from django.contrib.gis.geos import GEOSGeometry

from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.apis.geocoding import get_geocoding_data
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_NO_RESULT_MOCK, BAN_GEOCODING_API_RESULT_MOCK
from itou.utils.test import TestCase


class UtilsGeocodingTest(TestCase):
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_get_geocoding_data(self, mock_call_ban_geocoding_api):
        geocoding_data = mock_call_ban_geocoding_api()
        result = get_geocoding_data(geocoding_data)
        # Expected data comes from BAN_GEOCODING_API_RESULT_MOCK.
        expected = {
            "score": 0.587663373207207,
            "address_line_1": "10 Pl des Cinq Martyrs du Lycee Buffon",
            "number": "10",
            "lane": "Pl des Cinq Martyrs du Lycee Buffon",
            "address": "10 Pl des Cinq Martyrs du Lycee Buffon",
            "post_code": "75015",
            "insee_code": "75115",
            "city": "Paris",
            "longitude": 2.316754,
            "latitude": 48.838411,
            "coords": GEOSGeometry("POINT(2.316754 48.838411)"),
        }
        assert result == expected

    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_NO_RESULT_MOCK)
    def test_get_geocoding_data_error(self, mock_call_ban_geocoding_api):
        geocoding_data = mock_call_ban_geocoding_api()

        with pytest.raises(GeocodingDataError):
            get_geocoding_data(geocoding_data)
