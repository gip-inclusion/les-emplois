from unittest import mock

from django.contrib.gis.geos import GEOSGeometry
from django.core.exceptions import ValidationError
from django.template import Context, Template
from django.test import TestCase
from django.test.client import RequestFactory

from itou.prescribers.models import PrescriberOrganization
from itou.utils.apis.geocoding import process_geocoding_data
from itou.utils.apis.siret import process_siret_data
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK
from itou.utils.mocks.siret import API_INSEE_SIRET_RESULT_MOCK
from itou.utils.templatetags import format_filters
from itou.utils.urls import get_safe_url
from itou.utils.validators import validate_naf, validate_siret


class UtilsAddressMixinTest(TestCase):
    @mock.patch(
        "itou.utils.apis.geocoding.call_ban_geocoding_api",
        return_value=BAN_GEOCODING_API_RESULT_MOCK,
    )
    def test_geocode(self, mock_call_ban_geocoding_api):
        """
        Test `AddressMixin.geocode()`.
        Use `PrescriberOrganization` which inherits from abstract `AddressMixin`.
        """
        prescriber = PrescriberOrganization.objects.create(siret="12000015300011")
        prescriber.geocode("10 PL 5 MARTYRS LYCEE BUFFON", post_code="75015")

        # Expected data comes from BAN_GEOCODING_API_RESULT_MOCK.
        expected_address_line_1 = "10 Pl des Cinq Martyrs du Lycee Buffon"
        expected_post_code = "75015"
        expected_city = "Paris"
        expected_coords = "SRID=4326;POINT (2.316754 48.838411)"
        expected_latitude = 48.838411
        expected_longitude = 2.316754
        expected_geocoding_score = 0.587663373207207

        self.assertEqual(prescriber.address_line_1, expected_address_line_1)
        self.assertEqual(prescriber.post_code, expected_post_code)
        self.assertEqual(prescriber.city, expected_city)
        self.assertEqual(prescriber.coords, expected_coords)
        self.assertEqual(prescriber.geocoding_score, expected_geocoding_score)
        self.assertEqual(prescriber.latitude, expected_latitude)
        self.assertEqual(prescriber.longitude, expected_longitude)


class UtilsGeocodingTest(TestCase):
    @mock.patch(
        "itou.utils.apis.geocoding.call_ban_geocoding_api",
        return_value=BAN_GEOCODING_API_RESULT_MOCK,
    )
    def test_process_geocoding_data(self, mock_call_ban_geocoding_api):
        geocoding_data = mock_call_ban_geocoding_api()
        result = process_geocoding_data(geocoding_data)
        # Expected data comes from BAN_GEOCODING_API_RESULT_MOCK.
        expected = {
            "score": 0.587663373207207,
            "address_line_1": "10 Pl des Cinq Martyrs du Lycee Buffon",
            "post_code": "75015",
            "city": "Paris",
            "longitude": 2.316754,
            "latitude": 48.838411,
            "coords": GEOSGeometry("POINT(2.316754 48.838411)"),
        }
        self.assertEqual(result, expected)


class UtilsSiretTest(TestCase):
    @mock.patch(
        "itou.utils.apis.siret.call_insee_api", return_value=API_INSEE_SIRET_RESULT_MOCK
    )
    def test_process_siret_data(self, mock_call_insee_api):
        siret_data = mock_call_insee_api()
        result = process_siret_data(siret_data)
        # Expected data comes from API_INSEE_SIRET_RESULT_MOCK.
        expected = {
            "name": "DELEGATION GENERALE A L'EMPLOI ET A LA FORMATION PROFESSIONNELLE",
            "address": "10 PL 5 MARTYRS LYCEE BUFFON",
            "post_code": "75015",
        }
        self.assertEqual(result, expected)


class UtilsValidatorsTest(TestCase):
    def test_validate_naf(self):
        self.assertRaises(ValidationError, validate_naf, "1")
        self.assertRaises(ValidationError, validate_naf, "12254")
        self.assertRaises(ValidationError, validate_naf, "abcde")
        self.assertRaises(ValidationError, validate_naf, "1245789871")
        validate_naf("6201Z")

    def test_validate_siret(self):
        self.assertRaises(ValidationError, validate_siret, "1200001530001")
        self.assertRaises(ValidationError, validate_siret, "120000153000111")
        self.assertRaises(ValidationError, validate_siret, "1200001530001a")
        self.assertRaises(ValidationError, validate_siret, "azertyqwerty")
        validate_siret("12000015300011")


class UtilsTemplateTagsTestCase(TestCase):
    def test_url_add_query(self):
        """Test `url_add_query` template tag."""

        # Full URL.
        context = {
            "url": "https://itou.beta.gouv.fr/siae/search?distance=100&city=aubervilliers-93&page=55&page=1"
        }
        template = Template("{% load url_add_query %}" "{% url_add_query url page=2 %}")
        out = template.render(Context(context))
        expected = "https://itou.beta.gouv.fr/siae/search?distance=100&amp;city=aubervilliers-93&amp;page=2"
        self.assertEqual(out, expected)

        # Relative URL.
        context = {"url": "/siae/search?distance=50&city=metz-57"}
        template = Template(
            "{% load url_add_query %}" "{% url_add_query url page=22 %}"
        )
        out = template.render(Context(context))
        expected = "/siae/search?distance=50&amp;city=metz-57&amp;page=22"
        self.assertEqual(out, expected)

        # Empty URL.
        context = {"url": ""}
        template = Template("{% load url_add_query %}" "{% url_add_query url page=1 %}")
        out = template.render(Context(context))
        expected = "?page=1"
        self.assertEqual(out, expected)


class UtilsTemplateFiltersTestCase(TestCase):
    def test_format_phone(self):
        """Test `format_phone` template filter."""
        self.assertEqual(format_filters.format_phone(""), "")
        self.assertEqual(format_filters.format_phone("0102030405"), "01 02 03 04 05")


class UtilsEmailsTestCase(TestCase):
    def test_get_safe_url(self):
        """Test `urls.get_safe_url()`."""

        request = RequestFactory().get(
            "/?next=/siae/search%3Fdistance%3D100%26city%3Dstrasbourg-67"
        )
        url = get_safe_url(request, "next")
        expected = "/siae/search?distance=100&city=strasbourg-67"
        self.assertEqual(url, expected)

        request = RequestFactory().post(
            "/", data={"next": "/siae/search?distance=100&city=strasbourg-67"}
        )
        url = get_safe_url(request, "next")
        expected = "/siae/search?distance=100&city=strasbourg-67"
        self.assertEqual(url, expected)

        request = RequestFactory().get("/?next=https://evil.com/siae/search")
        url = get_safe_url(request, "next")
        expected = None
        self.assertEqual(url, expected)

        request = RequestFactory().post("/", data={"next": "https://evil.com"})
        url = get_safe_url(request, "next", fallback_url="/fallback")
        expected = "/fallback"
        self.assertEqual(url, expected)
