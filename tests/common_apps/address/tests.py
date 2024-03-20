from unittest import mock

import pytest
from django import forms
from django.contrib.gis.geos import Point

from itou.common_apps.address.departments import department_from_postcode
from itou.common_apps.address.forms import MandatoryAddressFormMixin, OptionalAddressFormMixin
from itou.common_apps.address.models import lat_lon_to_coords
from itou.prescribers.models import PrescriberOrganization
from itou.users.models import User
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_NO_RESULT_MOCK, BAN_GEOCODING_API_RESULT_MOCK
from tests.cities.factories import create_test_cities
from tests.users.factories import JobSeekerFactory
from tests.utils.test import TestCase


class UtilsAddressMixinTest(TestCase):
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_set_coords(self, _mock_call_ban_geocoding_api):
        """
        Test `AddressMixin.set_coords()`.
        Use `PrescriberOrganization` which inherits from abstract `AddressMixin`.
        """
        prescriber = PrescriberOrganization.objects.create(siret="12000015300011")

        assert prescriber.address_line_1 == ""
        assert prescriber.address_line_2 == ""
        assert prescriber.post_code == ""
        assert prescriber.city == ""
        assert prescriber.coords is None
        assert prescriber.geocoding_score is None
        assert prescriber.latitude is None
        assert prescriber.longitude is None

        prescriber.set_coords()
        prescriber.save()

        # Expected data comes from BAN_GEOCODING_API_RESULT_MOCK.
        expected_coords = "SRID=4326;POINT (2.316754 48.838411)"
        expected_latitude = 48.838411
        expected_longitude = 2.316754
        expected_geocoding_score = 0.587663373207207

        assert prescriber.coords == expected_coords
        assert prescriber.geocoding_score == expected_geocoding_score
        assert prescriber.latitude == expected_latitude
        assert prescriber.longitude == expected_longitude

    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_NO_RESULT_MOCK)
    def test_set_coords_with_bad_address(self, _mock_call_ban_geocoding_api):
        """
        Test `AddressMixin.set_coords()` with bad address.
        Use `PrescriberOrganization` which inherits from abstract `AddressMixin`.
        """
        prescriber = PrescriberOrganization.objects.create(siret="12000015300011")

        with pytest.raises(GeocodingDataError):
            prescriber.set_coords()


class UtilsDepartmentsTest(TestCase):
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


class DummyUserModelForm(OptionalAddressFormMixin, forms.ModelForm):
    """
    A dummy `ModelForm` using `OptionalAddressFormMixin` to be used in `UtilsOptionalAddressFormMixinTest`.
    """

    class Meta:
        model = User
        fields = [
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "department",
        ]


class UtilsOptionalAddressFormMixinTest(TestCase):
    """
    Test `OptionalAddressFormMixin`.
    """

    def test_empty_form(self):
        """
        An empty form is OK.
        """
        form_data = {}
        form = OptionalAddressFormMixin(data=form_data)
        assert form.is_valid()
        expected_cleaned_data = {
            "city_slug": "",
            "city": "",
            "address_line_1": "",
            "address_line_2": "",
            "post_code": "",
        }
        assert form.cleaned_data == expected_cleaned_data

    def test_missing_address_line_1(self):
        """
        `address_line_1` is missing but `address_line_2` exists.
        """
        form_data = {
            "city_slug": "",
            "city": "",
            "address_line_1": "",
            "address_line_2": "11 rue des pixels cassés",
            "post_code": "",
        }
        form = OptionalAddressFormMixin(data=form_data)
        assert not form.is_valid()
        assert form.errors["address_line_1"][0] == "Adresse : ce champ est obligatoire."
        assert form.errors["post_code"][0] == "Code postal : ce champ est obligatoire."
        assert form.errors["city"][0] == "Ville : ce champ est obligatoire."

    def test_fecth_city(self):
        """
        The city name should be fetched from the slug.
        """

        [city] = create_test_cities(["67"], num_per_department=1)

        form_data = {
            "city_slug": city.slug,
            "city": "",
            "address_line_1": "11 rue des pixels cassés",
            "address_line_2": "",
            "post_code": "67000",
        }

        form = OptionalAddressFormMixin(data=form_data)

        with self.assertNumQueries(1):
            assert form.is_valid()
            expected_cleaned_data = {
                "city_slug": city.slug,
                "city": city.name,
                "address_line_1": form_data["address_line_1"],
                "address_line_2": form_data["address_line_2"],
                "post_code": form_data["post_code"],
            }
            assert form.cleaned_data == expected_cleaned_data

    def test_with_instance(self):
        """
        If an instance is passed, `city` and `city_slug` should be prepopulated.
        """

        [city] = create_test_cities(["57"], num_per_department=1)

        user = JobSeekerFactory()
        user.address_line_1 = "11 rue des pixels cassés"
        user.department = city.department
        user.post_code = city.post_codes[0]
        user.city = city.name

        with self.assertNumQueries(1):
            form = DummyUserModelForm(data={}, instance=user)

            assert form.initial["city_slug"] == city.slug
            assert form.initial["city"] == city.name


class UtilsMandatoryAddressFormMixinTest(TestCase):
    """
    Test `MandatoryAddressFormMixin`.
    """

    def test_required_fields(self):
        """
        Test that `address_line_1`, `post_code` and `city` fields are required.
        """
        form_data = {}
        form = MandatoryAddressFormMixin(data=form_data)
        assert not form.is_valid()

        assert form.errors["address_line_1"][0] == "Ce champ est obligatoire."
        assert form.errors["post_code"][0] == "Ce champ est obligatoire."
        assert form.errors["city"][0] == "Ce champ est obligatoire."


class UtilsMiscTestCase(TestCase):
    def test_lat_lon_to_coords(self):
        assert lat_lon_to_coords(None, None) is None
        assert lat_lon_to_coords(1, None) is None
        assert lat_lon_to_coords(None, 1) is None
        assert lat_lon_to_coords(13, 42) == Point(42, 13)
