from unittest import mock

from django.test import TestCase

from itou.prescribers.models import PrescriberOrganization
from itou.utils.address.departments import department_from_postcode
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK


class UtilsAddressMixinTest(TestCase):
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_set_coords(self, mock_call_ban_geocoding_api):
        """
        Test `AddressMixin.set_coords()`.
        Use `PrescriberOrganization` which inherits from abstract `AddressMixin`.
        """
        prescriber = PrescriberOrganization.objects.create(siret="12000015300011")

        self.assertEqual(prescriber.address_line_1, "")
        self.assertEqual(prescriber.address_line_2, "")
        self.assertEqual(prescriber.post_code, "")
        self.assertEqual(prescriber.city, "")
        self.assertEqual(prescriber.coords, None)
        self.assertEqual(prescriber.geocoding_score, None)
        self.assertEqual(prescriber.latitude, None)
        self.assertEqual(prescriber.longitude, None)

        prescriber.set_coords("10 PL 5 MARTYRS LYCEE BUFFON", post_code="75015")
        prescriber.save()

        # Expected data comes from BAN_GEOCODING_API_RESULT_MOCK.
        expected_coords = "SRID=4326;POINT (2.316754 48.838411)"
        expected_latitude = 48.838411
        expected_longitude = 2.316754
        expected_geocoding_score = 0.587663373207207

        self.assertEqual(prescriber.coords, expected_coords)
        self.assertEqual(prescriber.geocoding_score, expected_geocoding_score)
        self.assertEqual(prescriber.latitude, expected_latitude)
        self.assertEqual(prescriber.longitude, expected_longitude)

    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_set_coords_and_address(self, mock_call_ban_geocoding_api):
        """
        Test `AddressMixin.set_coords_and_address()`.
        Use `PrescriberOrganization` which inherits from abstract `AddressMixin`.
        """
        prescriber = PrescriberOrganization.objects.create(siret="12000015300011")

        self.assertEqual(prescriber.address_line_1, "")
        self.assertEqual(prescriber.address_line_2, "")
        self.assertEqual(prescriber.post_code, "")
        self.assertEqual(prescriber.city, "")
        self.assertEqual(prescriber.coords, None)
        self.assertEqual(prescriber.geocoding_score, None)
        self.assertEqual(prescriber.latitude, None)
        self.assertEqual(prescriber.longitude, None)

        prescriber.set_coords_and_address("10 PL 5 MARTYRS LYCEE BUFFON", post_code="75015")
        prescriber.save()

        # Expected data comes from BAN_GEOCODING_API_RESULT_MOCK.
        expected_address_line_1 = "10 Pl des Cinq Martyrs du Lycee Buffon"
        expected_post_code = "75015"
        expected_city = "Paris"
        expected_coords = "SRID=4326;POINT (2.316754 48.838411)"
        expected_latitude = 48.838411
        expected_longitude = 2.316754
        expected_geocoding_score = 0.587663373207207

        self.assertEqual(prescriber.address_line_1, expected_address_line_1)
        self.assertEqual(prescriber.address_line_2, "")
        self.assertEqual(prescriber.post_code, expected_post_code)
        self.assertEqual(prescriber.city, expected_city)
        self.assertEqual(prescriber.coords, expected_coords)
        self.assertEqual(prescriber.geocoding_score, expected_geocoding_score)
        self.assertEqual(prescriber.latitude, expected_latitude)
        self.assertEqual(prescriber.longitude, expected_longitude)


class UtilsDepartmentsTest(TestCase):
    def test_department_from_postcode(self):
        # Corsica south == 2A
        post_codes = ["20000", "20137", "20700"]
        for post_code in post_codes:
            self.assertEqual(department_from_postcode(post_code), "2A")

        # Corsica north == 2B
        post_codes = ["20240", "20220", "20407", "20660"]
        for post_code in post_codes:
            self.assertEqual(department_from_postcode(post_code), "2B")

        # DOM
        post_codes = ["97500", "97000", "98800", "98000"]
        for post_code in post_codes:
            self.assertEqual(department_from_postcode(post_code), post_code[:3])

        # Any other city
        post_codes = ["13150", "30210", "17000"]
        for post_code in post_codes:
            self.assertEqual(department_from_postcode(post_code), post_code[:2])
