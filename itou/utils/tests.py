import copy
import datetime
import decimal
import functools
import importlib
import json
import logging
import uuid
from unittest import mock

import faker
import httpx
import pytest
import respx
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import ValidationError
from django.core.mail.message import EmailMessage
from django.http import HttpResponse
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from factory import Faker
from faker import Faker as fk

import itou.utils.json
import itou.utils.session
from itou.approvals.factories import SuspensionFactory
from itou.approvals.models import Suspension
from itou.common_apps.resume.forms import ResumeFormMixin
from itou.institutions.factories import InstitutionFactory, InstitutionWithMembershipFactory
from itou.job_applications.factories import JobApplicationFactory
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeFactory
from itou.siaes.models import Siae, SiaeMembership
from itou.users.enums import KIND_JOB_SEEKER, KIND_PRESCRIBER, KIND_SIAE_STAFF
from itou.users.factories import JobSeekerFactory, PrescriberFactory, UserFactory
from itou.users.models import User
from itou.utils import constants as global_constants, pagination
from itou.utils.apis import api_entreprise
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.apis.geocoding import get_geocoding_data
from itou.utils.apis.pole_emploi import PoleEmploiAPIBadResponse, PoleEmploiApiClient, PoleEmploiAPIException
from itou.utils.mocks.api_entreprise import ETABLISSEMENT_API_RESULT_MOCK, INSEE_API_RESULT_MOCK
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_NO_RESULT_MOCK, BAN_GEOCODING_API_RESULT_MOCK
from itou.utils.mocks.pole_emploi import (
    API_MAJPASS_RESULT_ERROR,
    API_MAJPASS_RESULT_OK,
    API_RECHERCHE_ERROR,
    API_RECHERCHE_RESULT_KNOWN,
)
from itou.utils.models import PkSupportRemark
from itou.utils.password_validation import CnilCompositionPasswordValidator
from itou.utils.perms.context_processors import get_current_organization_and_perms
from itou.utils.perms.user import get_user_info
from itou.utils.tasks import sanitize_mailjet_recipients
from itou.utils.templatetags import dict_filters, format_filters
from itou.utils.tokens import SIAE_SIGNUP_MAGIC_LINK_TIMEOUT, SiaeSignupTokenGenerator
from itou.utils.urls import get_absolute_url, get_external_link_markup, get_safe_url, get_tally_form_url
from itou.utils.validators import (
    alphanumeric,
    validate_af_number,
    validate_birthdate,
    validate_code_safir,
    validate_naf,
    validate_nir,
    validate_pole_emploi_id,
    validate_post_code,
    validate_siren,
    validate_siret,
)


def get_response_for_middlewaremixin(request):
    """
    `SessionMiddleware` inherits from `MiddlewareMixin` which requires
    a `get_response` argument since Django 4.0:
    https://github.com/django/django/pull/11828

    An empty `HttpResponse` does the trick.
    """
    return HttpResponse()


class ContextProcessorsGetCurrentOrganizationAndPermsTest(TestCase):
    def go_to_dashboard(self, user, establishment_session_key, establishment_pk):
        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        middleware = SessionMiddleware(get_response_for_middlewaremixin)
        middleware.process_request(request)
        request.session[establishment_session_key] = establishment_pk
        request.session.save()
        return request

    def test_siae_one_membership(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        self.assertTrue(siae.has_admin(user))

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=global_constants.ITOU_SESSION_CURRENT_SIAE_KEY,
            establishment_pk=siae.pk,
        )

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)
            assert result == {
                "current_siae": siae,
                "user_is_siae_admin": True,
                "user_siaes": [siae],
                "matomo_custom_variables": {
                    "account_id": user.pk,
                    "is_authenticated": "yes",
                    "account_type": "employer",
                    "account_sub_type": "employer_admin",
                    "account_current_siae_id": siae.pk,
                    "account_siae_ids": str(siae.pk),
                },
            }

    def test_siae_multiple_memberships(self):
        # Specify name to ensure alphabetical sorting order.
        siae1 = SiaeFactory(name="1", with_membership=True)
        user = siae1.members.first()
        self.assertTrue(siae1.has_admin(user))

        siae2 = SiaeFactory(name="2")
        siae2.members.add(user)
        self.assertFalse(siae2.has_admin(user))

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=global_constants.ITOU_SESSION_CURRENT_SIAE_KEY,
            establishment_pk=siae2.pk,
        )

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)
            assert result == {
                "current_siae": siae2,
                "user_is_siae_admin": False,
                "user_siaes": [siae1, siae2],
                "matomo_custom_variables": {
                    "account_id": user.pk,
                    "is_authenticated": "yes",
                    "account_type": "employer",
                    "account_sub_type": "employer_not_admin",
                    "account_current_siae_id": siae2.pk,
                    "account_siae_ids": f"{siae1.pk};{siae2.pk}",
                },
            }

    def test_prescriber_organization_one_membership(self):
        organization = PrescriberOrganizationWithMembershipFactory()
        user = organization.members.first()
        self.assertTrue(user.prescribermembership_set.get(organization=organization).is_admin)

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY,
            establishment_pk=organization.pk,
        )

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)
            assert result == {
                "current_prescriber_organization": organization,
                "user_prescriberorganizations": [organization],
                "user_is_prescriber_org_admin": True,
                "matomo_custom_variables": {
                    "account_id": user.pk,
                    "is_authenticated": "yes",
                    "account_type": "prescriber",
                    "account_sub_type": "prescriber_with_unauthorized_org",
                    "account_current_prescriber_org_id": organization.pk,
                    "account_organization_ids": str(organization.pk),
                },
            }

    def test_prescriber_organization_multiple_membership(self):
        # Specify name to ensure alphabetical sorting order.
        organization1 = PrescriberOrganizationWithMembershipFactory(name="1")
        user = organization1.members.first()
        self.assertTrue(user.prescribermembership_set.get(organization=organization1).is_admin)

        organization2 = PrescriberOrganizationWithMembershipFactory(name="2")
        organization2.members.add(user)

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY,
            establishment_pk=organization1.pk,
        )

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)
            assert result == {
                "current_prescriber_organization": organization1,
                "user_prescriberorganizations": [organization1, organization2],
                "user_is_prescriber_org_admin": True,
                "matomo_custom_variables": {
                    "account_id": user.pk,
                    "is_authenticated": "yes",
                    "account_type": "prescriber",
                    "account_sub_type": "prescriber_with_unauthorized_org",
                    "account_current_prescriber_org_id": organization1.pk,
                    "account_organization_ids": f"{organization1.pk};{organization2.pk}",
                },
            }

    def test_labor_inspector_one_institution(self):
        institution = InstitutionWithMembershipFactory()
        user = institution.members.first()
        self.assertTrue(user.institutionmembership_set.get(institution=institution).is_admin)

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=global_constants.ITOU_SESSION_CURRENT_INSTITUTION_KEY,
            establishment_pk=institution.pk,
        )

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)
            assert result == {
                "current_institution": institution,
                "user_institutions": [institution],
                "user_is_institution_admin": True,
                "matomo_custom_variables": {
                    "account_id": user.pk,
                    "is_authenticated": "yes",
                    "account_type": "labor_inspector",
                    "account_sub_type": "inspector_admin",
                    "account_institution_ids": str(institution.pk),
                    "account_current_institution_id": institution.pk,
                },
            }

    def test_labor_inspector_multiple_institutions(self):
        # Specify name to ensure alphabetical sorting order.
        institution1 = InstitutionWithMembershipFactory(name="1")
        user = institution1.members.first()
        self.assertTrue(user.institutionmembership_set.get(institution=institution1).is_admin)
        institution2 = InstitutionFactory(name="2")
        institution2.members.add(user)
        self.assertFalse(institution2.has_admin(user))

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=global_constants.ITOU_SESSION_CURRENT_INSTITUTION_KEY,
            establishment_pk=institution2.pk,
        )

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)
            assert result == {
                "current_institution": institution2,
                "user_institutions": [institution1, institution2],
                "user_is_institution_admin": False,
                "matomo_custom_variables": {
                    "account_id": user.pk,
                    "is_authenticated": "yes",
                    "account_type": "labor_inspector",
                    "account_sub_type": "inspector_not_admin",
                    "account_institution_ids": f"{institution1.pk};{institution2.pk}",
                    "account_current_institution_id": institution2.pk,
                },
            }


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
        self.assertEqual(result, expected)

    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_NO_RESULT_MOCK)
    def test_get_geocoding_data_error(self, mock_call_ban_geocoding_api):
        geocoding_data = mock_call_ban_geocoding_api()

        with self.assertRaises(GeocodingDataError):
            get_geocoding_data(geocoding_data)


class UtilsValidatorsTest(TestCase):
    def test_validate_alphanumeric(self):
        self.assertRaises(ValidationError, alphanumeric, "1245a_89871")
        alphanumeric("6201Z")

    def test_validate_code_safir(self):
        self.assertRaises(ValidationError, validate_code_safir, "1a3v5")
        self.assertRaises(ValidationError, validate_code_safir, "123456")
        alphanumeric("12345")

    def test_validate_naf(self):
        self.assertRaises(ValidationError, validate_naf, "1")
        self.assertRaises(ValidationError, validate_naf, "12254")
        self.assertRaises(ValidationError, validate_naf, "abcde")
        self.assertRaises(ValidationError, validate_naf, "1245789871")
        validate_naf("6201Z")

    def test_validate_siren(self):
        self.assertRaises(ValidationError, validate_siren, "12000015")
        self.assertRaises(ValidationError, validate_siren, "1200001531")
        self.assertRaises(ValidationError, validate_siren, "12000015a")
        self.assertRaises(ValidationError, validate_siren, "azertyqwe")
        validate_siren("120000153")

    def test_validate_siret(self):
        self.assertRaises(ValidationError, validate_siret, "1200001530001")
        self.assertRaises(ValidationError, validate_siret, "120000153000111")
        self.assertRaises(ValidationError, validate_siret, "1200001530001a")
        self.assertRaises(ValidationError, validate_siret, "azertyqwerty")
        validate_siret("12000015300011")

    def test_validate_post_code(self):
        self.assertRaises(ValidationError, validate_post_code, "")
        self.assertRaises(ValidationError, validate_post_code, "1234")
        self.assertRaises(ValidationError, validate_post_code, "123456")
        self.assertRaises(ValidationError, validate_post_code, "1234X")
        validate_post_code("12345")

    def test_validate_pole_emploi_id(self):
        self.assertRaises(ValidationError, validate_pole_emploi_id, "A2345678")
        self.assertRaises(ValidationError, validate_pole_emploi_id, "1234")
        self.assertRaises(ValidationError, validate_pole_emploi_id, "123412345654")
        self.assertRaises(ValidationError, validate_pole_emploi_id, "A234567É")
        validate_pole_emploi_id("12345678")
        validate_pole_emploi_id("1234567E")

    def test_validate_birthdate(self):
        # Min.
        self.assertRaises(ValidationError, validate_birthdate, datetime.date(1899, 12, 31))
        validate_birthdate(datetime.date(1900, 1, 1))
        # Max.
        max_date = timezone.localdate() - relativedelta(years=16)
        self.assertRaises(ValidationError, validate_birthdate, max_date + datetime.timedelta(days=1))
        self.assertRaises(ValidationError, validate_birthdate, max_date + datetime.timedelta(days=365))
        self.assertRaises(ValidationError, validate_birthdate, max_date)
        validate_birthdate(max_date - datetime.timedelta(days=3600))

    def test_validate_nir(self):
        # Valid number
        validate_nir("141068078200557")
        # Corse-du-Sud in lower case.
        validate_nir("141062a78200555")
        # Haute-Corse
        validate_nir("141062B78200582")
        # Valid number with fictitious month
        validate_nir("141208078200587")
        self.assertRaises(ValidationError, validate_nir, "123456789")
        self.assertRaises(ValidationError, validate_nir, "141068078200557123")
        # Should start with 1 or 2.
        self.assertRaises(ValidationError, validate_nir, "341208078200557")
        # Third group should be between 0 and 12.
        self.assertRaises(ValidationError, validate_nir, "141208078200557")
        # Last group should validate the first 13 characters.
        self.assertRaises(ValidationError, validate_nir, "141068078200520")

    def test_validate_af_number(self):
        # Dubious values.
        self.assertRaises(ValidationError, validate_af_number, "")
        self.assertRaises(ValidationError, validate_af_number, None)

        # Missing or incorrect suffix (should be A0M0 or alike).
        self.assertRaises(ValidationError, validate_af_number, "ACI063170007")
        self.assertRaises(ValidationError, validate_af_number, "ACI063170007Z1Z1")

        # Missing digit.
        self.assertRaises(ValidationError, validate_af_number, "EI08018002A1M1")
        self.assertRaises(ValidationError, validate_af_number, "AI08816001A1M1")

        # Correct values.
        validate_af_number("ACI063170007A0M0")
        validate_af_number("ACI063170007A0M1")
        validate_af_number("ACI063170007A1M1")
        validate_af_number("EI080180002A1M1")
        validate_af_number("EI59V182019A1M1")
        validate_af_number("AI088160001A1M1")
        validate_af_number("ETTI080180002A1M1")
        validate_af_number("ETTI59L181001A1M1")


class UtilsTemplateTagsTestCase(TestCase):
    def test_url_add_query(self):
        """Test `url_add_query` template tag."""

        base_url = "https://emplois.inclusion.beta.gouv.fr"
        # Full URL.
        context = {"url": f"{base_url}/siae/search?distance=100&city=aubervilliers-93&page=55&page=1"}
        template = Template("{% load url_add_query %}{% url_add_query url page=2 %}")
        out = template.render(Context(context))
        expected = f"{base_url}/siae/search?distance=100&amp;city=aubervilliers-93&amp;page=2"
        self.assertEqual(out, expected)

        # Relative URL.
        context = {"url": "/siae/search?distance=50&city=metz-57"}
        template = Template("{% load url_add_query %}{% url_add_query url page=22 %}")
        out = template.render(Context(context))
        expected = "/siae/search?distance=50&amp;city=metz-57&amp;page=22"
        self.assertEqual(out, expected)

        # Empty URL.
        context = {"url": ""}
        template = Template("{% load url_add_query %}{% url_add_query url page=1 %}")
        out = template.render(Context(context))
        expected = "?page=1"
        self.assertEqual(out, expected)

    def test_redirection_url(self):
        base_url = reverse("dashboard:index")
        redirect_field_value = reverse("home:hp")

        # Redirection value.
        context = {"redirect_field_name": "next", "redirect_field_value": redirect_field_value}
        template = Template(
            """
            {% load redirection_fields %}
            {% url "dashboard:index" %}{% redirection_url name=redirect_field_name value=redirect_field_value %}
        """
        )
        out = template.render(Context(context)).strip()
        expected = base_url + f"?next={redirect_field_value}"
        self.assertEqual(out, expected)

        # No redirection value.
        template = Template(
            """
            {% load redirection_fields %}
            {% url "dashboard:index" %}{% redirection_url name=redirect_field_name value=redirect_field_value %}
        """
        )
        out = template.render(Context()).strip()
        expected = base_url
        self.assertEqual(out, expected)

    def test_redirection_input_field(self):
        name = "next"
        value = reverse("home:hp")

        # Redirection value.
        context = {"redirect_field_name": name, "redirect_field_value": value}
        template = Template(
            """
            {% load redirection_fields %}
            {% redirection_input_field name=redirect_field_name value=redirect_field_value %}
        """
        )
        out = template.render(Context(context)).strip()
        expected = f'<input type="hidden" name="{name}" value="{value}">'
        self.assertEqual(out, expected)

        # No redirection expected.
        template = Template(
            """
            {% load redirection_fields %}
            {% redirection_input_field name=redirect_field_name value=redirect_field_value %}
        """
        )
        out = template.render(Context()).strip()
        expected = ""
        self.assertEqual(out, expected)

    def test_call_method(self):
        """Test `call_method` template tag."""
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        context = {"siae": siae, "user": user}
        template = Template("{% load call_method %}{% call_method siae 'has_member' user %}")
        out = template.render(Context(context))
        expected = "True"
        self.assertEqual(out, expected)

    def test_pluralizefr(self):
        """Test `pluralizefr` template tag."""
        template = Template("{% load str_filters %}Résultat{{ counter|pluralizefr }}")
        out = template.render(Context({"counter": 0}))
        self.assertEqual(out, "Résultat")
        out = template.render(Context({"counter": 1}))
        self.assertEqual(out, "Résultat")
        out = template.render(Context({"counter": 10}))
        self.assertEqual(out, "Résultats")

    def test_mask_unless(self):
        template = Template("""{% load str_filters %}{{ value|mask_unless:predicate }}""")

        self.assertEqual(
            template.render(Context({"value": "Firstname Lastname", "predicate": True})),
            "Firstname Lastname",
        )
        self.assertEqual(
            template.render(Context({"value": "Firstname Lastname", "predicate": False})),
            "F… L…",
        )
        self.assertEqual(
            template.render(Context({"value": "Firstname Middlename Lastname", "predicate": False})),
            "F… M… L…",
        )
        self.assertEqual(
            template.render(Context({"value": "Firstname Middlename Lastname1-Lastname2", "predicate": False})),
            "F… M… L…",
        )
        self.assertEqual(
            template.render(Context({"value": " Firstname  Middlename   Lastname ", "predicate": False})),
            "F… M… L…",
        )
        self.assertEqual(
            template.render(Context({"value": "\tFirstname\t\tMiddlename\tLastname\t\t", "predicate": False})),
            "F… M… L…",
        )

    @override_settings(TALLY_URL="https://foobar")
    def test_tally_url_custom_template_tag(self):
        test_id = 1234
        context = {
            "test_id": test_id,
        }
        template = Template("{% load tally %}url:{% tally_form_url 'abcde' pk=test_id hard='coded'%}")
        out = template.render(Context(context))

        self.assertEqual(f"url:{get_tally_form_url('abcde', pk=test_id, hard='coded')}", out)


class UtilsTemplateFiltersTestCase(TestCase):
    def test_format_phone(self):
        """Test `format_phone` template filter."""
        self.assertEqual(format_filters.format_phone(""), "")
        self.assertEqual(format_filters.format_phone("0102030405"), "01 02 03 04 05")

    def test_get_dict_item(self):
        """Test `get_dict_item` template filter."""
        my_dict = {"key1": "value1", "key2": "value2"}
        self.assertEqual(dict_filters.get_dict_item(my_dict, "key1"), "value1")
        self.assertEqual(dict_filters.get_dict_item(my_dict, "key2"), "value2")

    def test_format_siret(self):
        # Don't format invalid SIRET
        self.assertEqual(format_filters.format_siret("1234"), "1234")
        self.assertEqual(format_filters.format_siret(None), "None")
        # SIREN
        self.assertEqual(format_filters.format_siret("123456789"), "123 456 789")
        # SIRET
        self.assertEqual(format_filters.format_siret("12345678912345"), "123 456 789 12345")

    def test_format_nir(self):
        test_cases = [
            (
                "141068078200557",
                '<span>1</span><span class="ml-1">41</span><span class="ml-1">06</span>'
                '<span class="ml-1">80</span><span class="ml-1">782</span><span class="ml-1">005</span>'
                '<span class="ml-1">57</span>',
            ),
            (
                " 1 41 06 80 782 005 57",
                '<span>1</span><span class="ml-1">41</span><span class="ml-1">06</span>'
                '<span class="ml-1">80</span><span class="ml-1">782</span><span class="ml-1">005</span>'
                '<span class="ml-1">57</span>',
            ),
            ("", ""),
            ("12345678910", "12345678910"),
        ]
        for nir, expected in test_cases:
            with self.subTest(nir):
                self.assertEqual(format_filters.format_nir(nir), expected)

    def test_format_approval_number(self):
        test_cases = [
            ("", ""),
            ("XXXXX3500001", '<span>XXXXX</span><span class="ml-1">35</span><span class="ml-1">00001</span>'),
            # Actual formatting does not really matter, just verify it does not crash.
            ("foo", '<span>foo</span><span class="ml-1"></span><span class="ml-1"></span>'),
        ]
        for number, expected in test_cases:
            with self.subTest(number):
                self.assertEqual(format_filters.format_approval_number(number), expected)


class UtilsEmailsTestCase(TestCase):
    def test_get_safe_url(self):
        """Test `urls.get_safe_url()`."""

        request = RequestFactory().get("/?next=/siae/search%3Fdistance%3D100%26city%3Dstrasbourg-67")
        url = get_safe_url(request, "next")
        expected = "/siae/search?distance=100&city=strasbourg-67"
        self.assertEqual(url, expected)

        request = RequestFactory().post("/", data={"next": "/siae/search?distance=100&city=strasbourg-67"})
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

    def test_get_absolute_url(self):
        url = get_absolute_url()
        self.assertEqual(f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}/", url)

        # With path
        path = "awesome/team/"
        url = get_absolute_url(path)
        self.assertEqual(f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}/{path}", url)

        # Escape first slash
        path = "/awesome/team/"
        url = get_absolute_url(path)
        self.assertEqual(f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}/awesome/team/", url)

    def test_get_external_link_markup(self):
        url = "https://emplois.inclusion.beta.gouv.fr"
        text = "Lien vers une ressource externe"
        expected = (
            f'<a href="{url}" rel="noopener" target="_blank" aria-label="Ouverture dans un nouvel onglet">{text}</a>'
        )
        self.assertEqual(get_external_link_markup(url=url, text=text), expected)


class PermsUserTest(TestCase):
    def test_get_user_info_for_siae_staff(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        middleware = SessionMiddleware(get_response_for_middlewaremixin)
        middleware.process_request(request)
        # Simulate ItouCurrentOrganizationMiddleware.
        request.session[global_constants.ITOU_SESSION_CURRENT_SIAE_KEY] = siae.pk
        request.session.save()

        user_info = get_user_info(request)
        self.assertEqual(user_info.user, user)
        self.assertEqual(user_info.kind, KIND_SIAE_STAFF)
        self.assertEqual(user_info.prescriber_organization, None)
        self.assertEqual(user_info.is_authorized_prescriber, False)
        self.assertEqual(user_info.siae, siae)

    def test_get_user_info_for_prescriber(self):
        prescriber_organization = PrescriberOrganizationWithMembershipFactory()
        user = prescriber_organization.members.first()

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        middleware = SessionMiddleware(get_response_for_middlewaremixin)
        middleware.process_request(request)
        # Simulate ItouCurrentOrganizationMiddleware.
        request.session[global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY] = prescriber_organization.pk
        request.session.save()

        user_info = get_user_info(request)
        self.assertEqual(user_info.user, user)
        self.assertEqual(user_info.kind, KIND_PRESCRIBER)
        self.assertEqual(user_info.prescriber_organization, prescriber_organization)
        self.assertEqual(user_info.is_authorized_prescriber, False)
        self.assertEqual(user_info.siae, None)

    def test_get_user_info_for_authorized_prescriber(self):
        prescriber_organization = PrescriberOrganizationWithMembershipFactory(is_authorized=True)
        user = prescriber_organization.members.first()

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        middleware = SessionMiddleware(get_response_for_middlewaremixin)
        middleware.process_request(request)
        # Simulate ItouCurrentOrganizationMiddleware.
        request.session[global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY] = prescriber_organization.pk
        request.session.save()

        user_info = get_user_info(request)
        self.assertEqual(user_info.user, user)
        self.assertEqual(user_info.kind, KIND_PRESCRIBER)
        self.assertEqual(user_info.prescriber_organization, prescriber_organization)
        self.assertEqual(user_info.is_authorized_prescriber, True)
        self.assertEqual(user_info.siae, None)

    def test_get_user_info_for_prescriber_without_organisation(self):
        user = PrescriberFactory()

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        middleware = SessionMiddleware(get_response_for_middlewaremixin)
        middleware.process_request(request)
        request.session.save()

        user_info = get_user_info(request)
        self.assertEqual(user_info.user, user)
        self.assertEqual(user_info.kind, KIND_PRESCRIBER)
        self.assertEqual(user_info.prescriber_organization, None)
        self.assertEqual(user_info.is_authorized_prescriber, False)
        self.assertEqual(user_info.siae, None)

    def test_get_user_info_for_job_seeker(self):
        user = JobSeekerFactory()

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        middleware = SessionMiddleware(get_response_for_middlewaremixin)
        middleware.process_request(request)
        request.session.save()

        user_info = get_user_info(request)
        self.assertEqual(user_info.user, user)
        self.assertEqual(user_info.kind, KIND_JOB_SEEKER)
        self.assertEqual(user_info.prescriber_organization, None)
        self.assertEqual(user_info.is_authorized_prescriber, False)
        self.assertEqual(user_info.siae, None)


class MockedSiaeSignupTokenGenerator(SiaeSignupTokenGenerator):
    def __init__(self, now):
        self._now_val = now

    def _now(self):
        return self._now_val


class SiaeSignupTokenGeneratorTest(TestCase):
    def test_make_token(self):
        siae = Siae.objects.create()
        p0 = SiaeSignupTokenGenerator()
        tk1 = p0.make_token(siae)
        self.assertIs(p0.check_token(siae, tk1), True)

    def test_10265(self):
        """
        The token generated for a siae created in the same request
        will work correctly.
        """
        siae = Siae.objects.create(email="itou@example.com")
        siae_reload = Siae.objects.get(email="itou@example.com")
        p0 = MockedSiaeSignupTokenGenerator(datetime.datetime.now())
        tk1 = p0.make_token(siae)
        tk2 = p0.make_token(siae_reload)
        self.assertEqual(tk1, tk2)

    def test_timeout(self):
        """The token is valid after n seconds, but no greater."""
        # Uses a mocked version of SiaeSignupTokenGenerator so we can change
        # the value of 'now'.
        siae = Siae.objects.create()
        p0 = SiaeSignupTokenGenerator()
        tk1 = p0.make_token(siae)
        p1 = MockedSiaeSignupTokenGenerator(
            datetime.datetime.now() + datetime.timedelta(seconds=(SIAE_SIGNUP_MAGIC_LINK_TIMEOUT - 1))
        )
        self.assertIs(p1.check_token(siae, tk1), True)
        p2 = MockedSiaeSignupTokenGenerator(
            datetime.datetime.now() + datetime.timedelta(seconds=(SIAE_SIGNUP_MAGIC_LINK_TIMEOUT + 1))
        )
        self.assertIs(p2.check_token(siae, tk1), False)

    def test_check_token_with_nonexistent_token_and_user(self):
        siae = Siae.objects.create()
        p0 = SiaeSignupTokenGenerator()
        tk1 = p0.make_token(siae)
        self.assertIs(p0.check_token(None, tk1), False)
        self.assertIs(p0.check_token(siae, None), False)
        self.assertIs(p0.check_token(siae, tk1), True)

    def test_any_new_signup_invalidates_past_token(self):
        """
        Tokens are based on siae.members.count() so that
        any new signup invalidates past tokens.
        """
        siae = Siae.objects.create()
        p0 = SiaeSignupTokenGenerator()
        tk1 = p0.make_token(siae)
        self.assertIs(p0.check_token(siae, tk1), True)
        user = User()
        user.save()
        membership = SiaeMembership()
        membership.user = user
        membership.siae = siae
        membership.save()
        self.assertIs(p0.check_token(siae, tk1), False)


class CnilCompositionPasswordValidatorTest(SimpleTestCase):
    def test_validate(self):

        # Good passwords.

        # lower + upper + special char
        self.assertIsNone(CnilCompositionPasswordValidator().validate("!*pAssWOrD"))
        # lower + upper + digit
        self.assertIsNone(CnilCompositionPasswordValidator().validate("MYp4ssW0rD"))
        # lower + upper + digit + special char
        self.assertIsNone(CnilCompositionPasswordValidator().validate("M+p4ssW0rD"))

        # Wrong passwords.

        expected_error = CnilCompositionPasswordValidator.HELP_MSG

        with self.assertRaises(ValidationError) as error:
            # Only lower + upper
            CnilCompositionPasswordValidator().validate("MYpAssWOrD")
        self.assertEqual(error.exception.messages, [expected_error])
        self.assertEqual(error.exception.error_list[0].code, "cnil_composition")

        with self.assertRaises(ValidationError) as error:
            # Only lower + digit
            CnilCompositionPasswordValidator().validate("myp4ssw0rd")
        self.assertEqual(error.exception.messages, [expected_error])
        self.assertEqual(error.exception.error_list[0].code, "cnil_composition")

    def test_help_text(self):
        self.assertEqual(CnilCompositionPasswordValidator().get_help_text(), CnilCompositionPasswordValidator.HELP_MSG)


@override_settings(
    API_INSEE_BASE_URL="https://fake.insee.url", API_INSEE_CONSUMER_KEY="foo", API_INSEE_CONSUMER_SECRET="bar"
)
class INSEEApiTest(SimpleTestCase):
    @respx.mock
    def test_access_token(self):
        endpoint = respx.post(f"{settings.API_INSEE_BASE_URL}/token").respond(200, json=INSEE_API_RESULT_MOCK)

        access_token = api_entreprise.get_access_token()

        self.assertTrue(endpoint.called)
        self.assertIn(b"grant_type=client_credentials", endpoint.calls.last.request.content)
        self.assertTrue(endpoint.calls.last.request.headers["Authorization"].startswith("Basic "))
        self.assertEqual(access_token, INSEE_API_RESULT_MOCK["access_token"])

    @respx.mock
    def test_access_token_with_http_error(self):
        respx.post(f"{settings.API_INSEE_BASE_URL}/token").respond(400)

        with self.assertLogs(api_entreprise.logger, logging.ERROR) as cm:
            access_token = api_entreprise.get_access_token()

        self.assertIsNone(access_token)
        self.assertIn("Failed to retrieve an access token", cm.records[0].message)
        self.assertIs(cm.records[0].exc_info[0], httpx.HTTPStatusError)

    @respx.mock
    def test_access_token_with_json_error(self):
        respx.post(f"{settings.API_INSEE_BASE_URL}/token").respond(200, content=b"not-json")

        with self.assertLogs(api_entreprise.logger, logging.ERROR) as cm:
            access_token = api_entreprise.get_access_token()

        self.assertIsNone(access_token)
        self.assertIn("Failed to retrieve an access token", cm.records[0].message)
        self.assertIs(cm.records[0].exc_info[0], json.JSONDecodeError)


@override_settings(
    API_INSEE_BASE_URL="https://fake.insee.url",
    API_ENTREPRISE_BASE_URL="https://api.entreprise.fake.com",
    API_INSEE_CONSUMER_KEY="foo",
    API_INSEE_CONSUMER_SECRET="bar",
)
class ApiEntrepriseTest(SimpleTestCase):
    def setUp(self):
        super().setUp()

        self.token_endpoint = respx.post(f"{settings.API_INSEE_BASE_URL}/token").respond(
            200,
            json=INSEE_API_RESULT_MOCK,
        )

        self.siret_endpoint = respx.get(f"{settings.API_ENTREPRISE_BASE_URL}/siret/26570134200148")

    @respx.mock
    def test_etablissement_get_or_error(self):
        self.siret_endpoint.respond(200, json=ETABLISSEMENT_API_RESULT_MOCK)

        etablissement, error = api_entreprise.etablissement_get_or_error("26570134200148")

        self.assertIsNone(error)
        self.assertEqual(etablissement.name, "CENTRE COMMUNAL D'ACTION SOCIALE")
        self.assertEqual(etablissement.address_line_1, "22 RUE DU WAD BILLY")
        self.assertEqual(etablissement.address_line_2, "22-24")
        self.assertEqual(etablissement.post_code, "57000")
        self.assertEqual(etablissement.city, "METZ")
        self.assertEqual(etablissement.department, "57")
        self.assertFalse(etablissement.is_closed)
        self.assertTrue(etablissement.is_head_office)

    @respx.mock
    def test_etablissement_get_or_error_with_closed_status(self):
        data = copy.deepcopy(ETABLISSEMENT_API_RESULT_MOCK)
        data["etablissement"]["periodesEtablissement"][0]["etatAdministratifEtablissement"] = "F"
        self.siret_endpoint.respond(200, json=data)

        etablissement, error = api_entreprise.etablissement_get_or_error("26570134200148")

        self.assertIsNone(error)
        self.assertTrue(etablissement.is_closed)

    @respx.mock
    def test_etablissement_get_or_error_without_token(self):
        self.token_endpoint.respond(404)

        result = api_entreprise.etablissement_get_or_error("whatever")

        self.assertEqual(result, (None, "Problème de connexion à la base Sirene. Essayez ultérieurement."))

    @respx.mock
    def test_etablissement_get_or_error_with_request_error(self):
        self.siret_endpoint.mock(side_effect=httpx.RequestError)

        with self.assertLogs(api_entreprise.logger, logging.ERROR) as cm:
            result = api_entreprise.etablissement_get_or_error("26570134200148")

        self.assertEqual(result, (None, "Problème de connexion à la base Sirene. Essayez ultérieurement."))
        self.assertTrue(cm.records[0].message.startswith("A request to the INSEE API failed"))

    @respx.mock
    def test_etablissement_get_or_error_with_other_http_bad_request_error(self):
        self.siret_endpoint.respond(400)

        result = api_entreprise.etablissement_get_or_error("26570134200148")

        self.assertEqual(result, (None, "Erreur dans le format du SIRET : « 26570134200148 »."))

    @respx.mock
    def test_etablissement_get_or_error_with_other_http_forbidden_error(self):
        self.siret_endpoint.respond(403)

        result = api_entreprise.etablissement_get_or_error("26570134200148")

        self.assertEqual(result, (None, "Cette entreprise a exercé son droit d'opposition auprès de l'INSEE."))

    @respx.mock
    def test_etablissement_get_or_error_with_other_http_not_found_error(self):
        self.siret_endpoint.respond(404)

        result = api_entreprise.etablissement_get_or_error("26570134200148")

        self.assertEqual(result, (None, "SIRET « 26570134200148 » non reconnu."))

    @respx.mock
    def test_etablissement_get_or_error_with_http_error(self):
        self.siret_endpoint.respond(401)

        with self.assertLogs(api_entreprise.logger, logging.ERROR) as cm:
            result = api_entreprise.etablissement_get_or_error("26570134200148")

        self.assertEqual(result, (None, "Problème de connexion à la base Sirene. Essayez ultérieurement."))
        self.assertTrue(cm.records[0].message.startswith("Error while fetching"))

    @respx.mock
    def test_etablissement_get_or_error_when_content_is_not_json(self):
        self.siret_endpoint.respond(200, content=b"not-json")

        with self.assertLogs(api_entreprise.logger, logging.ERROR) as cm:
            result = api_entreprise.etablissement_get_or_error("26570134200148")

        self.assertEqual(result, (None, "Le format de la réponse API Entreprise est non valide."))
        self.assertTrue(cm.records[0].message.startswith("Invalid format of response from API Entreprise"))
        self.assertIs(cm.records[0].exc_info[0], json.JSONDecodeError)

    @respx.mock
    def test_etablissement_get_or_error_when_content_is_missing_data(self):
        self.siret_endpoint.respond(200, json={})

        with self.assertLogs(api_entreprise.logger, logging.ERROR) as cm:
            result = api_entreprise.etablissement_get_or_error("26570134200148")

        self.assertEqual(result, (None, "Le format de la réponse API Entreprise est non valide."))
        self.assertTrue(cm.records[0].message.startswith("Invalid format of response from API Entreprise"))
        self.assertIs(cm.records[0].exc_info[0], KeyError)

    @respx.mock
    def test_etablissement_get_or_error_when_content_is_missing_historical_data(self):
        data = copy.deepcopy(ETABLISSEMENT_API_RESULT_MOCK)
        data["etablissement"]["periodesEtablissement"] = []
        self.siret_endpoint.respond(200, json=data)

        with self.assertLogs(api_entreprise.logger, logging.ERROR) as cm:
            result = api_entreprise.etablissement_get_or_error("26570134200148")

        self.assertEqual(result, (None, "Le format de la réponse API Entreprise est non valide."))
        self.assertTrue(cm.records[0].message.startswith("Invalid format of response from API Entreprise"))
        self.assertIs(cm.records[0].exc_info[0], IndexError)

    @respx.mock
    def test_etablissement_get_or_error_with_missing_address_number(self):
        data = copy.deepcopy(ETABLISSEMENT_API_RESULT_MOCK)
        data["etablissement"]["adresseEtablissement"]["numeroVoieEtablissement"] = None
        self.siret_endpoint.respond(200, json=data)

        etablissement, error = api_entreprise.etablissement_get_or_error("26570134200148")

        self.assertIsNone(error)
        self.assertEqual(etablissement.address_line_1, "RUE DU WAD BILLY")

    @respx.mock
    def test_etablissement_get_or_error_with_empty_address(self):
        data = copy.deepcopy(ETABLISSEMENT_API_RESULT_MOCK)
        data["etablissement"]["adresseEtablissement"] = {
            "complementAdresseEtablissement": None,
            "numeroVoieEtablissement": None,
            "typeVoieEtablissement": None,
            "libelleVoieEtablissement": None,
            "codePostalEtablissement": None,
            "libelleCommuneEtablissement": None,
            "codeCommuneEtablissement": None,
        }
        self.siret_endpoint.respond(200, json=data)

        etablissement, error = api_entreprise.etablissement_get_or_error("26570134200148")

        self.assertIsNone(error)
        self.assertEqual(etablissement.address_line_1, None)
        self.assertEqual(etablissement.address_line_2, None)
        self.assertEqual(etablissement.post_code, None)
        self.assertEqual(etablissement.city, None)
        self.assertEqual(etablissement.department, None)


class PoleEmploiAPIClientTest(TestCase):
    def setUp(self) -> None:
        self.api_client = PoleEmploiApiClient(
            "https://some.auth.domain", "https://some-authentication-domain.fr", "foobar", "pe-secret"
        )
        respx.post(self.api_client.token_url).respond(
            200, json={"token_type": "foo", "access_token": "batman", "expires_in": 3600}
        )

    @respx.mock
    def test_get_token_nominal(self):
        now = timezone.now()
        self.api_client._refresh_token(at=now)
        self.assertEqual(self.api_client.token, "foo batman")
        self.assertEqual(self.api_client.expires_at, now + datetime.timedelta(seconds=3600))

    @respx.mock
    def test_get_token_fails(self):
        job_seeker = JobSeekerFactory()
        respx.post(self.api_client.token_url).mock(side_effect=httpx.ConnectTimeout)
        with self.assertRaises(PoleEmploiAPIException) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.nir
            )
        self.assertEqual(ctx.exception.error_code, "http_error")

    @respx.mock
    def test_recherche_individu_certifie_api_nominal(self):
        job_seeker = JobSeekerFactory()
        respx.post(self.api_client.recherche_individu_url).respond(200, json=API_RECHERCHE_RESULT_KNOWN)
        id_national = self.api_client.recherche_individu_certifie(
            job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.nir
        )
        self.assertEqual(id_national, "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ")

        # now with weird payloads
        job_seeker.first_name = "marié%{-christine}  aéïèêë " + "a" * 50
        job_seeker.last_name = "gh'îkñ Bind-n'qici " + "b" * 50
        id_national = self.api_client.recherche_individu_certifie(
            job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.nir
        )
        payload = json.loads(respx.calls.last.request.content)
        self.assertEqual(payload["nomNaissance"], "GH'IKN BIND-N'QICI BBBBBB")  # 25 chars
        self.assertEqual(payload["prenom"], "MARIE-CHRISTI")  # 13 chars

    @respx.mock
    def test_recherche_individu_certifie_individual_api_errors(self):
        job_seeker = JobSeekerFactory()
        respx.post(self.api_client.recherche_individu_url).respond(200, json=API_RECHERCHE_ERROR)
        with self.assertRaises(PoleEmploiAPIBadResponse) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.nir
            )
        self.assertEqual(ctx.exception.response_code, "R010")

    @respx.mock
    def test_recherche_individu_certifie_retryable_errors(self):
        job_seeker = JobSeekerFactory()

        respx.post(self.api_client.recherche_individu_url).respond(401, json="")
        with self.assertRaises(PoleEmploiAPIException) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.nir
            )
        self.assertEqual(ctx.exception.error_code, 401)

        job_seeker = JobSeekerFactory()
        respx.post(self.api_client.recherche_individu_url).mock(side_effect=httpx.ConnectTimeout)
        with self.assertRaises(PoleEmploiAPIException) as ctx:
            self.api_client.recherche_individu_certifie(
                job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, job_seeker.nir
            )
        self.assertEqual(ctx.exception.error_code, "http_error")

    @respx.mock
    def test_mise_a_jour_pass_iae_success_with_approval_accepted(self):
        """
        Nominal scenario: an approval is **accepted**
        HTTP 200 + codeSortie = S001 is the only way mise_a_jour_pass_iae does not raise.
        """
        job_application = JobApplicationFactory(with_approval=True)
        respx.post(self.api_client.mise_a_jour_url).respond(200, json=API_MAJPASS_RESULT_OK)
        # we really don't care about the arguments there
        self.api_client.mise_a_jour_pass_iae(job_application.approval, "foo", "bar", 42, "DEAD")

    @respx.mock
    def test_mise_a_jour_pass_iae_failure(self):
        job_application = JobApplicationFactory(with_approval=True)
        # non-S001 codeSortie
        respx.post(self.api_client.mise_a_jour_url).respond(200, json=API_MAJPASS_RESULT_ERROR)
        with self.assertRaises(PoleEmploiAPIBadResponse):
            self.api_client.mise_a_jour_pass_iae(job_application.approval, "foo", "bar", 42, "DEAD")

        # timeout
        respx.post(self.api_client.mise_a_jour_url).mock(side_effect=httpx.ConnectTimeout)
        with self.assertRaises(PoleEmploiAPIException) as ctx:
            self.api_client.mise_a_jour_pass_iae(job_application.approval, "foo", "bar", 42, "DEAD")
        self.assertEqual(ctx.exception.error_code, "http_error")

        # auth failed
        respx.post(self.api_client.mise_a_jour_url).respond(401, json={})
        with self.assertRaises(PoleEmploiAPIException):
            self.api_client.mise_a_jour_pass_iae(job_application.approval, "foo", "bar", 42, "DEAD")
        self.assertEqual(ctx.exception.error_code, "http_error")


class UtilsEmailsSplitRecipientTest(TestCase):
    """
    Test behavior of email backend when sending emails with more than 50 recipients
    (Mailjet API Limit)
    """

    def test_email_copy(self):
        fake_email = Faker("email", locale="fr_FR")
        message = EmailMessage(from_email="unit-test@tests.com", body="xxx", to=[fake_email], subject="test")
        result = sanitize_mailjet_recipients(message)

        self.assertEqual(1, len(result))

        self.assertEqual("xxx", result[0].body)
        self.assertEqual("unit-test@tests.com", result[0].from_email)
        self.assertEqual(fake_email, result[0].to[0])
        self.assertEqual("test", result[0].subject)

    def test_dont_split_emails(self):
        recipients = []
        # Only one email is needed
        for _ in range(49):
            recipients.append(Faker("email", locale="fr_FR"))

        message = EmailMessage(from_email="unit-test@tests.com", body="", to=recipients)
        result = sanitize_mailjet_recipients(message)

        self.assertEqual(1, len(result))
        self.assertEqual(49, len(result[0].to))

    def test_must_split_emails(self):
        # 2 emails are needed; one with 50 the other with 25
        recipients = []
        for _ in range(75):
            recipients.append(Faker("email", locale="fr_FR"))

        message = EmailMessage(from_email="unit-test@tests.com", body="", to=recipients)
        result = sanitize_mailjet_recipients(message)

        self.assertEqual(2, len(result))
        self.assertEqual(50, len(result[0].to))
        self.assertEqual(25, len(result[1].to))


class ResumeFormMixinTest(TestCase):
    @override_settings(S3_STORAGE_ENDPOINT_DOMAIN="foobar.com")
    def test_ensure_link_safe_hosting(self):
        form = ResumeFormMixin(data={"resume_link": "https://www.evil.com/virus.pdf"})
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["resume_link"][0], "Le CV proposé ne provient pas d'une source de confiance.")

        form = ResumeFormMixin(data={"resume_link": "https://foobar.com/safe.pdf"})
        self.assertTrue(form.is_valid())

    def test_resume_is_optional(self):
        form = ResumeFormMixin(data={})
        self.assertTrue(form.is_valid())

        form = ResumeFormMixin(data={"resume_link": None})
        self.assertTrue(form.is_valid())

        form = ResumeFormMixin(data={"resume_link": ""})
        self.assertTrue(form.is_valid())


class SupportRemarkAdminViewsTest(TestCase):
    def test_add_support_remark_to_suspension(self):
        user = UserFactory()
        self.client.force_login(user)

        today = timezone.localdate()
        job_app = JobApplicationFactory(with_approval=True)
        approval = job_app.approval

        suspension = SuspensionFactory(
            approval=approval,
            start_at=today,
            end_at=today + relativedelta(months=2),
            reason=Suspension.Reason.BROKEN_CONTRACT.value,
        )

        url = reverse("admin:approvals_suspension_change", args=[suspension.pk])

        # Not enough perms.
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        user.is_staff = True
        user.save()

        # Add needed perms
        suspension_content_type = ContentType.objects.get_for_model(Suspension)
        permission = Permission.objects.get(content_type=suspension_content_type, codename="change_suspension")
        user.user_permissions.add(permission)
        remark_content_type = ContentType.objects.get_for_model(PkSupportRemark)
        permission = Permission.objects.get(content_type=remark_content_type, codename="view_pksupportremark")
        user.user_permissions.add(permission)
        permission = Permission.objects.get(content_type=remark_content_type, codename="add_pksupportremark")
        user.user_permissions.add(permission)

        # With good perms.
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        fake = fk(locale="fr_FR")
        fake_remark = fake.sentence()

        # Get initial data for suspension form
        post_data = response.context["adminform"].form.initial

        # Compose manually dict for remark inlines fields because context doesn't provide it easily
        post_data.update(
            {
                "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": "1",
                "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": "0",
                "utils-pksupportremark-content_type-object_id-MIN_NUM_FORMS": "0",
                "utils-pksupportremark-content_type-object_id-MAX_NUM_FORMS": "1",
                "utils-pksupportremark-content_type-object_id-0-remark": fake_remark,
                "utils-pksupportremark-content_type-object_id-0-id": "",
                "utils-pksupportremark-content_type-object_id-__prefix__-remark": "",
                "utils-pksupportremark-content_type-object_id-__prefix__-id": "",
                "_save": "Enregistrer",
            }
        )
        self.client.post(url, data=post_data)

        # Is the remark created ?
        remark = PkSupportRemark.objects.filter(content_type=suspension_content_type, object_id=suspension.pk).first()
        self.assertEqual(remark.remark, fake_remark)

        # Is the remark displayed in admin change form ?
        response = self.client.get(url)
        self.assertContains(response, escape(fake_remark))


class SessionNamespaceTest(TestCase):
    def _get_session_store(self):
        return importlib.import_module(settings.SESSION_ENGINE).SessionStore()

    def test_magic_method(self):
        session = self._get_session_store()
        ns_name = faker.Faker().word()

        ns = itou.utils.session.SessionNamespace(session, ns_name)

        # __contains__ + __repr__
        for value_to_test in [{}, [], (), set()]:
            session[ns_name] = value_to_test
            self.assertFalse("unknown" in ns)
            self.assertEqual(repr(ns), f"<SessionNamespace({value_to_test!r})>")

        for value_to_test in [{"value": "42"}, ["value"], ("value",), {"value"}]:
            session[ns_name] = value_to_test
            self.assertTrue("value" in ns)
            self.assertEqual(repr(ns), f"<SessionNamespace({value_to_test!r})>")

    def test_api_method(self):
        session = self._get_session_store()
        ns_name = faker.Faker().word()

        ns = itou.utils.session.SessionNamespace(session, ns_name)
        self.assertNotIn(ns_name, session)  # The namespace doesn't yet exist in the session

        # .init()
        ns.init({"key": "value"})
        self.assertIn(ns_name, session)
        self.assertEqual(session[ns_name], {"key": "value"})

        # .get()
        self.assertEqual(ns.get("key"), "value")
        self.assertIs(ns.get("not_existing_key", None), None)
        self.assertIs(ns.get("not_existing_key"), ns.NOT_SET)
        self.assertFalse(ns.get("not_existing_key"))

        # .set()
        ns.set("key2", "value2")
        self.assertEqual(ns.get("key2"), "value2")
        self.assertEqual(session[ns_name], {"key": "value", "key2": "value2"})

        # .update()
        ns.update({"key3": "value3"})
        self.assertEqual(ns.get("key3"), "value3")
        self.assertEqual(session[ns_name], {"key": "value", "key2": "value2", "key3": "value3"})

        ns.update({"key": "other_value"})
        self.assertEqual(ns.get("key"), "other_value")
        self.assertEqual(session[ns_name], {"key": "other_value", "key2": "value2", "key3": "value3"})

        # .as_dict()
        self.assertEqual(ns.as_dict(), {"key": "other_value", "key2": "value2", "key3": "value3"})

        # .exists() + .delete()
        self.assertTrue(ns.exists())
        ns.delete()
        self.assertNotIn(ns_name, session)
        self.assertFalse(ns.exists())

    def test_class_method(self):
        session = self._get_session_store()

        # .create_temporary()
        ns = itou.utils.session.SessionNamespace.create_temporary(session)
        self.assertIsInstance(ns, itou.utils.session.SessionNamespace)
        self.assertEqual(str(uuid.UUID(ns.name)), ns.name)
        self.assertNotIn(ns.name, session)  # .init() wasn't called


class JSONTest(TestCase):

    SYMMETRIC_CONVERSION = [
        (None, "null"),
        (False, "false"),
        (True, "true"),
        (42, "42"),
        (3.14, "3.14"),
        ("value", '"value"'),
        ([1, "2", None, True, False], '[1, "2", null, true, false]'),
        ({"key": "value"}, '{"key": "value"}'),
        (datetime.time(), '{"__type__": "datetime.time", "value": "00:00:00"}'),
        (datetime.date(2001, 1, 1), '{"__type__": "datetime.date", "value": "2001-01-01"}'),
        (datetime.datetime(2001, 1, 1), '{"__type__": "datetime.datetime", "value": "2001-01-01T00:00:00"}'),
        (
            datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc),
            '{"__type__": "datetime.datetime", "value": "2001-01-01T00:00:00+00:00"}',
        ),
        (datetime.timedelta(), '{"__type__": "datetime.timedelta", "value": "P0DT00H00M00S"}'),
        (decimal.Decimal("-inf"), '{"__type__": "decimal.Decimal", "value": "-Infinity"}'),
        (
            uuid.UUID("fc8495d2-a7ea-44d9-b858-b88413a6f849"),
            '{"__type__": "uuid.UUID", "value": "fc8495d2-a7ea-44d9-b858-b88413a6f849"}',
        ),
    ]

    ASYMMETRIC_CONVERSION = [
        ((1, "2", None, True, False), '[1, "2", null, true, false]', [1, "2", None, True, False]),
    ]

    def test_encoder(self):
        dumps = functools.partial(json.dumps, cls=itou.utils.json.JSONEncoder)

        for obj, expected in self.SYMMETRIC_CONVERSION:
            self.assertEqual(dumps(obj), expected)

        for obj, expected, *_ in self.ASYMMETRIC_CONVERSION:
            self.assertEqual(dumps(obj), expected)

        model_object = UserFactory()
        self.assertEqual(dumps(model_object), str(model_object.pk))

    def test_decode(self):
        loads = functools.partial(json.loads, cls=itou.utils.json.JSONDecoder)

        for expected, s in self.SYMMETRIC_CONVERSION:
            self.assertEqual(loads(s), expected)

        for *_, s, expected in self.ASYMMETRIC_CONVERSION:
            self.assertEqual(loads(s), expected)


@pytest.mark.no_django_db
class TestPaginator:
    def test_paginator_unique_page(self):
        object_list = range(10)
        paginator = pagination.ItouPaginator(object_list, 10)
        page = paginator.get_page(1)
        assert not page.display_pager

    def test_paginator_multiple_pages(self):
        object_list = range(100)
        paginator = pagination.ItouPaginator(object_list, 5)
        page = paginator.get_page(10)
        assert page.display_pager
        assert page.pages_to_display == range(5, 16)

    def test_pager_unique_page(self):
        object_list = range(10)
        pager = pagination.pager(object_list, 10)
        assert not pager.display_pager

    def test_pager_multiple_pages(self):
        object_list = range(100)
        pager = pagination.pager(object_list, 10, items_per_page=5)
        assert pager.display_pager
        assert pager.pages_to_display == range(5, 16)
