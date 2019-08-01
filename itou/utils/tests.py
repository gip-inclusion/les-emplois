from unittest import mock

from django.contrib.gis.geos import GEOSGeometry
from django.core.exceptions import ValidationError
from django.test import TestCase

from itou.prescribers.models import Prescriber
from itou.utils.geocoding import process_geocoding_data
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK
from itou.utils.mocks.siret import API_INSEE_SIRET_RESULT_MOCK
from itou.utils.siret import process_siret_data
from itou.utils.validators import validate_naf, validate_siret


class UtilsAddressMixinTest(TestCase):

    @mock.patch('itou.utils.geocoding.call_ban_geocoding_api', return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_geocode(self, mock_call_ban_geocoding_api):
        """
        Test `AddressMixin.geocode()`.
        Use `Prescriber` which inherits from abstract `AddressMixin`.
        """
        prescriber = Prescriber.objects.create(siret='12000015300011')
        prescriber.geocode("10 PL 5 MARTYRS LYCEE BUFFON", "75015")

        # Expected data comes from BAN_GEOCODING_API_RESULT_MOCK.
        expected_address_line_1 = "10 Pl des Cinq Martyrs du Lycee Buffon"
        expected_zipcode = "75015"
        expected_city = "Paris"
        expected_coords = "SRID=4326;POINT (2.316754 48.838411)"
        expected_latitude = 48.838411
        expected_longitude = 2.316754
        expected_geocoding_score = 0.587663373207207

        self.assertEqual(prescriber.address_line_1, expected_address_line_1)
        self.assertEqual(prescriber.zipcode, expected_zipcode)
        self.assertEqual(prescriber.city, expected_city)
        self.assertEqual(prescriber.coords, expected_coords)
        self.assertEqual(prescriber.geocoding_score, expected_geocoding_score)
        self.assertEqual(prescriber.latitude, expected_latitude)
        self.assertEqual(prescriber.longitude, expected_longitude)


class UtilsGeocodingTest(TestCase):

    @mock.patch('itou.utils.geocoding.call_ban_geocoding_api', return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_process_geocoding_data(self, mock_call_ban_geocoding_api):
        geocoding_data = mock_call_ban_geocoding_api()
        result = process_geocoding_data(geocoding_data)
        # Expected data comes from BAN_GEOCODING_API_RESULT_MOCK.
        expected = {
            'score': 0.587663373207207,
            'address_line_1': '10 Pl des Cinq Martyrs du Lycee Buffon',
            'zipcode': '75015',
            'city': 'Paris',
            'longitude': 2.316754,
            'latitude': 48.838411,
            'coords': GEOSGeometry("POINT(2.316754 48.838411)"),
        }
        self.assertEqual(result, expected)


class UtilsSiretTest(TestCase):

    @mock.patch('itou.utils.siret.call_insee_api', return_value=API_INSEE_SIRET_RESULT_MOCK)
    def test_process_siret_data(self, mock_call_insee_api):
        siret_data = mock_call_insee_api()
        result = process_siret_data(siret_data)
        # Expected data comes from API_INSEE_SIRET_RESULT_MOCK.
        expected = {
            'name': "DELEGATION GENERALE A L'EMPLOI ET A LA FORMATION PROFESSIONNELLE",
            'address': '10 PL 5 MARTYRS LYCEE BUFFON',
            'zipcode': '75015',
        }
        self.assertEqual(result, expected)


class UtilsValidatorsTest(TestCase):

    def test_validate_naf(self):
        self.assertRaises(ValidationError, validate_naf, '1')
        self.assertRaises(ValidationError, validate_naf, '12254')
        self.assertRaises(ValidationError, validate_naf, 'abcde')
        self.assertRaises(ValidationError, validate_naf, '1245789871')
        validate_naf('6201Z')

    def test_validate_siret(self):
        self.assertRaises(ValidationError, validate_siret, '1200001530001')
        self.assertRaises(ValidationError, validate_siret, '120000153000111')
        self.assertRaises(ValidationError, validate_siret, '1200001530001a')
        self.assertRaises(ValidationError, validate_siret, 'azertyqwerty')
        validate_siret('12000015300011')
