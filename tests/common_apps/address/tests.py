import pytest
from django.contrib.gis.geos import Point

from itou.common_apps.address.departments import department_from_postcode
from itou.common_apps.address.models import lat_lon_to_coords
from itou.prescribers.models import PrescriberOrganization
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_NO_RESULT_MOCK, BAN_GEOCODING_API_RESULT_MOCK
from tests.prescribers.factories import PrescriberOrganizationFactory


class TestUtilsAddressMixinTest:
    def test_geocode_address(self, mocker):
        """
        Test `AddressMixin.geocode_address()`.
        Use `PrescriberOrganization` which inherits from abstract `AddressMixin`.
        """
        mocker.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
        org = PrescriberOrganizationFactory(
            siret="12000015300011", address_line_1="3 rue Machin", post_code="11000", city="Mars"
        )

        assert org.address_line_1 == "3 rue Machin"
        assert org.address_line_2 == ""
        assert org.post_code == "11000"
        assert org.city == "Mars"
        assert org.coords is None
        assert org.geocoding_score is None
        assert org.latitude is None
        assert org.longitude is None

        org.geocode_address()
        org.save()

        # Expected data comes from BAN_GEOCODING_API_RESULT_MOCK.
        expected_coords = "SRID=4326;POINT (2.316754 48.838411)"
        expected_latitude = 48.838411
        expected_longitude = 2.316754
        expected_geocoding_score = 0.5197687103594081

        assert org.coords == expected_coords
        assert org.geocoding_score == expected_geocoding_score
        assert org.latitude == expected_latitude
        assert org.longitude == expected_longitude

    def test_geocode_address_with_bad_address(self, mocker):
        """
        Test `AddressMixin.geocode_address()` with bad address.
        Use `PrescriberOrganization` which inherits from abstract `AddressMixin`.
        """
        mocker.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_NO_RESULT_MOCK)
        prescriber = PrescriberOrganization.objects.create(siret="12000015300011")

        with pytest.raises(GeocodingDataError):
            prescriber.geocode_address()


class TestUtilsDepartments:
    def test_department_from_postcode(self):
        # Corsica south == 2A
        post_codes = ["20000", "20137", "20700"]
        for post_code in post_codes:
            assert department_from_postcode(post_code) == "2A"

        # Corsica north == 2B
        post_codes = ["20240", "20220", "20407", "20660"]
        for post_code in post_codes:
            assert department_from_postcode(post_code) == "2B"

        # DOM
        post_codes = ["97500", "97000", "98800", "98000"]
        for post_code in post_codes:
            assert department_from_postcode(post_code) == post_code[:3]

        # Any other city
        post_codes = ["13150", "30210", "17000"]
        for post_code in post_codes:
            assert department_from_postcode(post_code) == post_code[:2]


class TestUtilsMisc:
    def test_lat_lon_to_coords(self):
        assert lat_lon_to_coords(None, None) is None
        assert lat_lon_to_coords(1, None) is None
        assert lat_lon_to_coords(None, 1) is None
        assert lat_lon_to_coords(13, 42) == Point(42, 13)
