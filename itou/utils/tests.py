import datetime
from collections import OrderedDict
from unittest import mock

import httpx
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

from itou.approvals.factories import SuspensionFactory
from itou.approvals.models import Suspension
from itou.common_apps.resume.forms import ResumeFormMixin
from itou.institutions.factories import InstitutionFactory, InstitutionWithMembershipFactory
from itou.job_applications.factories import JobApplicationFactory, JobApplicationWithApprovalFactory
from itou.job_applications.models import JobApplicationWorkflow
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeFactory, SiaeWithMembershipFactory
from itou.siaes.models import Siae, SiaeMembership
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory, PrescriberFactory, UserFactory
from itou.users.models import User
from itou.utils.apis.api_entreprise import etablissement_get_or_error
from itou.utils.apis.geocoding import process_geocoding_data
from itou.utils.apis.pole_emploi import (
    POLE_EMPLOI_PASS_APPROVED,
    POLE_EMPLOI_PASS_REFUSED,
    PoleEmploiIndividu,
    PoleEmploiMiseAJourPassIAEException,
    mise_a_jour_pass_iae,
    recherche_individu_certifie_api,
)
from itou.utils.emails import sanitize_mailjet_recipients
from itou.utils.mocks.api_entreprise import ETABLISSEMENT_API_RESULT_MOCK
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK
from itou.utils.mocks.pole_emploi import (
    POLE_EMPLOI_MISE_A_JOUR_PASS_API_RESULT_ERROR_MOCK,
    POLE_EMPLOI_MISE_A_JOUR_PASS_API_RESULT_OK_MOCK,
    POLE_EMPLOI_RECHERCHE_INDIVIDU_CERTIFIE_API_RESULT_ERROR_MOCK,
    POLE_EMPLOI_RECHERCHE_INDIVIDU_CERTIFIE_API_RESULT_KNOWN_MOCK,
)
from itou.utils.models import PkSupportRemark
from itou.utils.password_validation import CnilCompositionPasswordValidator
from itou.utils.perms.context_processors import get_current_organization_and_perms
from itou.utils.perms.user import KIND_JOB_SEEKER, KIND_PRESCRIBER, KIND_SIAE_STAFF, get_user_info
from itou.utils.templatetags import dict_filters, format_filters
from itou.utils.tokens import SIAE_SIGNUP_MAGIC_LINK_TIMEOUT, SiaeSignupTokenGenerator
from itou.utils.urls import get_absolute_url, get_external_link_markup, get_safe_url
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
    """Test `itou.utils.perms.context_processors.get_current_organization_and_perms` processor."""

    @property
    def default_result(self):
        return {
            "current_prescriber_organization": None,
            "current_siae": None,
            "current_institution": None,
            "user_is_prescriber_org_admin": False,
            "user_is_siae_admin": False,
            "user_is_institution_admin": False,
            "user_siaes": [],
            "user_prescriberorganizations": [],
            "user_institutions": [],
            "matomo_custom_variables": OrderedDict(
                [("is_authenticated", "yes"), ("account_type", None), ("account_sub_type", None)]
            ),
        }

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
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        self.assertTrue(siae.has_admin(user))

        request = self.go_to_dashboard(
            user=user, establishment_session_key=settings.ITOU_SESSION_CURRENT_SIAE_KEY, establishment_pk=siae.pk
        )

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)
            expected = self.default_result | {
                "current_siae": siae,
                "user_is_siae_admin": True,
                "user_siaes": [siae],
                "matomo_custom_variables": OrderedDict(
                    [("is_authenticated", "yes"), ("account_type", "employer"), ("account_sub_type", "employer_admin")]
                ),
            }
            self.assertDictEqual(expected, result)

    def test_siae_multiple_memberships(self):

        siae1 = SiaeWithMembershipFactory()
        user = siae1.members.first()
        self.assertTrue(siae1.has_admin(user))

        siae2 = SiaeFactory()
        siae2.members.add(user)
        self.assertFalse(siae2.has_admin(user))

        request = self.go_to_dashboard(
            user=user, establishment_session_key=settings.ITOU_SESSION_CURRENT_SIAE_KEY, establishment_pk=siae2.pk
        )

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)

            expected = self.default_result | {
                "current_siae": siae2,
                "user_siaes": [siae1, siae2],
                "user_is_siae_admin": False,
                "matomo_custom_variables": OrderedDict(
                    [
                        ("is_authenticated", "yes"),
                        ("account_type", "employer"),
                        ("account_sub_type", "employer_not_admin"),
                    ]
                ),
            }
            self.assertDictEqual(expected, result)

    def test_prescriber_organization_one_membership(self):
        organization = PrescriberOrganizationWithMembershipFactory()
        user = organization.members.first()
        self.assertTrue(user.prescribermembership_set.get(organization=organization).is_admin)

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY,
            establishment_pk=organization.pk,
        )

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)
            expected = self.default_result | {
                "current_prescriber_organization": organization,
                "user_prescriberorganizations": [organization],
                "user_is_prescriber_org_admin": True,
                "matomo_custom_variables": OrderedDict(
                    [
                        ("is_authenticated", "yes"),
                        ("account_type", "prescriber"),
                        ("account_sub_type", "prescriber_with_unauthorized_org"),
                    ]
                ),
            }
            self.assertDictEqual(expected, result)

    def test_prescriber_organization_multiple_membership(self):

        organization1 = PrescriberOrganizationWithMembershipFactory()
        user = organization1.members.first()
        self.assertTrue(user.prescribermembership_set.get(organization=organization1).is_admin)

        organization2 = PrescriberOrganizationWithMembershipFactory()
        organization2.members.add(user)

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY,
            establishment_pk=organization1.pk,
        )

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)
            expected = self.default_result | {
                "current_prescriber_organization": organization1,
                "user_prescriberorganizations": [organization1, organization2],
                "user_is_prescriber_org_admin": True,
                "matomo_custom_variables": OrderedDict(
                    [
                        ("is_authenticated", "yes"),
                        ("account_type", "prescriber"),
                        ("account_sub_type", "prescriber_with_unauthorized_org"),
                    ]
                ),
            }
            self.assertDictEqual(expected, result)

    def test_labor_inspector_one_institution(self):
        institution = InstitutionWithMembershipFactory()
        user = institution.members.first()
        self.assertTrue(user.institutionmembership_set.get(institution=institution).is_admin)

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=settings.ITOU_SESSION_CURRENT_INSTITUTION_KEY,
            establishment_pk=institution.pk,
        )

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)
            expected = self.default_result | {
                "current_institution": institution,
                "user_institutions": [institution],
                "user_is_institution_admin": True,
                "matomo_custom_variables": OrderedDict(
                    [
                        ("is_authenticated", "yes"),
                        ("account_type", "labor_inspector"),
                        ("account_sub_type", "inspector_admin"),
                    ]
                ),
            }
            self.assertDictEqual(expected, result)

    def test_labor_inspector_multiple_institutions(self):
        institution1 = InstitutionWithMembershipFactory()
        user = institution1.members.first()
        self.assertTrue(user.institutionmembership_set.get(institution=institution1).is_admin)
        institution2 = InstitutionFactory()
        institution2.members.add(user)
        self.assertFalse(institution2.has_admin(user))

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=settings.ITOU_SESSION_CURRENT_INSTITUTION_KEY,
            establishment_pk=institution2.pk,
        )

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)
            expected = self.default_result | {
                "current_institution": institution2,
                "user_institutions": [institution1, institution2],
                "user_is_institution_admin": False,
                "matomo_custom_variables": OrderedDict(
                    [
                        ("is_authenticated", "yes"),
                        ("account_type", "labor_inspector"),
                        ("account_sub_type", "inspector_not_admin"),
                    ]
                ),
            }
            self.assertDictEqual(expected, result)


class UtilsGeocodingTest(TestCase):
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_process_geocoding_data(self, mock_call_ban_geocoding_api):
        geocoding_data = mock_call_ban_geocoding_api()
        result = process_geocoding_data(geocoding_data)
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
        max_date = datetime.datetime.now().date() - relativedelta(years=16)
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

    def test_call_method(self):
        """Test `call_method` template tag."""
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        context = {"siae": siae, "user": user}
        template = Template("{% load call_method %}{% call_method siae 'has_member' user %}")
        out = template.render(Context(context))
        expected = "True"
        self.assertEqual(out, expected)


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
        self.assertEqual(format_filters.format_nir("141068078200557"), "1 41 06 80 782 005 57")
        self.assertEqual(format_filters.format_nir(" 1 41 06 80 782 005 57"), "1 41 06 80 782 005 57")


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
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        middleware = SessionMiddleware(get_response_for_middlewaremixin)
        middleware.process_request(request)
        # Simulate ItouCurrentOrganizationMiddleware.
        request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY] = siae.pk
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
        request.session[settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY] = prescriber_organization.pk
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
        request.session[settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY] = prescriber_organization.pk
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


class ApiEntrepriseTest(SimpleTestCase):
    @respx.mock
    def test_etablissement_api(self):
        siret = "26570134200148"
        respx.get(f"{settings.API_ENTREPRISE_BASE_URL}/etablissements/{siret}").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )

        etablissement, error = etablissement_get_or_error(siret)

        self.assertIsNone(error)
        self.assertEqual(etablissement.name, "CENTRE COMMUNAL D'ACTION SOCIALE")
        self.assertEqual(etablissement.address_line_1, "22 RUE DU WAD BILLY")
        self.assertEqual(etablissement.address_line_2, "22-24")
        self.assertEqual(etablissement.post_code, "57000")
        self.assertEqual(etablissement.city, "METZ")
        self.assertEqual(etablissement.department, "57")
        self.assertFalse(etablissement.is_closed)
        self.assertTrue(etablissement.is_head_office)


class PoleEmploiIndividuTest(TestCase):
    def test_name_conversion_for_special_characters(self):
        individual = PoleEmploiIndividu(
            "marie christine", "Bind n'qici ", datetime.date(1979, 6, 3), "152062441001270"
        )
        individual2 = PoleEmploiIndividu(
            "marié%{-christine}", "Bind-n'qici ", datetime.date(1979, 6, 3), "152062441001270"
        )
        # After clarification from PE, names should be truncated, so here we are
        self.assertEqual(individual.first_name, "MARIE-CHRISTI")
        self.assertEqual(individual2.first_name, "MARIE-CHRISTI")
        self.assertEqual(individual.last_name, "BIND N'QICI ")
        self.assertEqual(individual2.last_name, "BIND-N'QICI ")

    def test_name_conversion_for_accents(self):
        """first name and last name should not have accents, because Pole Emploi'S API cannot handle them"""
        individual = PoleEmploiIndividu("aéïèêë", "gh'îkñ", datetime.date(1979, 6, 3), "152062441001270")

        self.assertEqual(individual.first_name, "AEIEEE")
        self.assertEqual(individual.last_name, "GH'IKN")

    def test_name_length(self):
        """first name and last name have a maximum length (from PE’s API point of view)
        and should be truncated if its not the case"""
        individual = PoleEmploiIndividu("a" * 50, "b" * 50, datetime.date(1979, 6, 3), "152062441001270")

        self.assertEqual(len(individual.first_name), 13)
        self.assertEqual(len(individual.last_name), 25)


class PoleEmploiTest(TestCase):
    """All the test cases around function recherche_individu_certifie_api and mise_a_jour_pass_iae"""

    @mock.patch(
        "httpx.post",
        return_value=httpx.Response(200, json=POLE_EMPLOI_RECHERCHE_INDIVIDU_CERTIFIE_API_RESULT_KNOWN_MOCK),
    )
    def test_recherche_individu_certifie_api_nominal(self, mock_post):
        individual = PoleEmploiIndividu("EVARISTE", "GALOIS", datetime.date(1979, 6, 3), "152062441001270")
        individu_result = recherche_individu_certifie_api(individual, "some_valid_token")

        self.assertTrue(individu_result.is_valid)
        self.assertEqual(individu_result.id_national_demandeur, "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ")
        self.assertEqual(individu_result.code_sortie, "S001")

    @mock.patch(
        "httpx.post",
        return_value=httpx.Response(200, json=POLE_EMPLOI_RECHERCHE_INDIVIDU_CERTIFIE_API_RESULT_ERROR_MOCK),
    )
    def test_recherche_individu_certifie_individual_not_found(self, mock_post):
        individual = PoleEmploiIndividu("EVARISTE", "GALOIS", datetime.date(1979, 6, 3), "152062441001270")
        individu_result = recherche_individu_certifie_api(individual, "some_valid_token")

        self.assertEqual(individu_result.code_sortie, "R010")
        self.assertFalse(individu_result.is_valid())

    @mock.patch(
        "httpx.post",
        return_value=httpx.Response(401, json=""),
    )
    def test_recherche_individu_certifie_invalid_token(self, mock_post):
        individual = PoleEmploiIndividu("EVARISTE", "GALOIS", datetime.date(1979, 6, 3), "152062441001270")
        with self.assertRaises(PoleEmploiMiseAJourPassIAEException):
            individu_result = recherche_individu_certifie_api(individual, "broken_token")
            self.assertIsNone(individu_result)

    @mock.patch(
        "httpx.post",
        return_value=httpx.Response(200, json=POLE_EMPLOI_MISE_A_JOUR_PASS_API_RESULT_OK_MOCK),
    )
    def test_mise_a_jour_pass_iae_success_with_approval_accepted(self, mock_post):
        """
        Nominal scenario: an approval is **accepted**
        HTTP 200 + codeSortie = S001 is the only way mise_a_jour_pass_iae will return True"""
        job_application = JobApplicationWithApprovalFactory()
        result = mise_a_jour_pass_iae(
            job_application, POLE_EMPLOI_PASS_APPROVED, "some_valid_encrypted_identifier", "some_valid_token"
        )
        mock_post.assert_called()
        self.assertTrue(result)

    @mock.patch(
        "httpx.post",
        return_value=httpx.Response(200, json=POLE_EMPLOI_MISE_A_JOUR_PASS_API_RESULT_OK_MOCK),
    )
    def test_mise_a_jour_pass_iae_success_with_approval_refused(self, mock_post):
        """
        Nominal scenario: an approval is **refused**
        HTTP 200 + codeSortie = S001 is the only way mise_a_jour_pass_iae will return True"""
        job_application = JobApplicationFactory()
        result = mise_a_jour_pass_iae(
            job_application, POLE_EMPLOI_PASS_REFUSED, "some_valid_encrypted_identifier", "some_valid_token"
        )
        mock_post.assert_called()
        self.assertTrue(result)

    @mock.patch(
        "httpx.post",
        return_value=httpx.Response(200, json=POLE_EMPLOI_MISE_A_JOUR_PASS_API_RESULT_ERROR_MOCK),
    )
    def test_mise_a_jour_pass_iae_failure(self, mock_post):
        """
        If the API answers with a non-S001 codeSortie (this is something in the json output)
        mise_a_jour_pass_iae will return false
        """
        job_application = JobApplicationWithApprovalFactory()
        with self.assertRaises(PoleEmploiMiseAJourPassIAEException):
            mise_a_jour_pass_iae(
                job_application, POLE_EMPLOI_PASS_APPROVED, "some_valid_encrypted_identifier", "some_valid_token"
            )
            mock_post.assert_called()

    @mock.patch(
        "httpx.post",
        raises=httpx.ConnectTimeout,
    )
    def test_mise_a_jour_pass_iae_timeout(self, mock_post):
        """
        If the API answers with a non-S001 codeSortie (this is something in the json output)
        mise_a_jour_pass_iae will return false
        """
        job_application = JobApplicationWithApprovalFactory()
        with self.assertRaises(PoleEmploiMiseAJourPassIAEException):
            mise_a_jour_pass_iae(
                job_application, POLE_EMPLOI_PASS_APPROVED, "some_valid_encrypted_identifier", "some_valid_token"
            )
            mock_post.assert_called()

    @mock.patch(
        "httpx.post",
        return_value=httpx.Response(401, json=""),
    )
    def test_mise_a_jour_pass_iae_invalid_token(self, mock_post):
        """If the API answers with a non-200 http code, mise_a_jour_pass_iae will return false"""
        job_application = JobApplicationWithApprovalFactory()
        with self.assertRaises(PoleEmploiMiseAJourPassIAEException):
            mise_a_jour_pass_iae(
                job_application, POLE_EMPLOI_PASS_APPROVED, "some_valid_encrypted_identifier", "some_valid_token"
            )
            mock_post.assert_called()


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
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        today = timezone.now().date()
        job_app = JobApplicationWithApprovalFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
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
