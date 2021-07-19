import datetime
from collections import OrderedDict
from unittest import mock

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import ValidationError
from django.core.mail.message import EmailMessage
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, TestCase
from factory import Faker

from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeFactory, SiaeWithMembershipFactory
from itou.siaes.models import Siae, SiaeMembership
from itou.users.factories import JobSeekerFactory, PrescriberFactory
from itou.users.models import User
from itou.utils.apis.api_entreprise import EtablissementAPI
from itou.utils.apis.geocoding import process_geocoding_data
from itou.utils.apis.pole_emploi import PoleEmploiRechercheIndividuCertifieAPI
from itou.utils.emails import sanitize_mailjet_recipients
from itou.utils.mocks.api_entreprise import ETABLISSEMENT_API_RESULT_MOCK
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK
from itou.utils.mocks.pole_emploi import (
    POLE_EMPLOI_RECHERCHE_INDIVIDU_CERTIFIE_API_RESULT_ERROR_MOCK,
    POLE_EMPLOI_RECHERCHE_INDIVIDU_CERTIFIE_API_RESULT_KNOWN_MOCK,
)
from itou.utils.password_validation import CnilCompositionPasswordValidator
from itou.utils.perms.context_processors import get_current_organization_and_perms
from itou.utils.perms.user import KIND_JOB_SEEKER, KIND_PRESCRIBER, KIND_SIAE_STAFF, get_user_info
from itou.utils.resume.forms import ResumeFormMixin
from itou.utils.templatetags import dict_filters, format_filters
from itou.utils.tokens import SIAE_SIGNUP_MAGIC_LINK_TIMEOUT, SiaeSignupTokenGenerator
from itou.utils.urls import get_absolute_url, get_external_link_markup, get_safe_url
from itou.utils.validators import (
    alphanumeric,
    validate_af_number,
    validate_birthdate,
    validate_code_safir,
    validate_naf,
    validate_pole_emploi_id,
    validate_post_code,
    validate_siren,
    validate_siret,
)


class ContextProcessorsGetCurrentOrganizationAndPermsTest(TestCase):
    """Test `itou.utils.perms.context_processors.get_current_organization_and_perms` processor."""

    @property
    def default_result(self):
        return {
            "current_prescriber_organization": None,
            "current_siae": None,
            "current_institution": None,
            "user_is_admin": None,
            "user_siaes": [],
            "user_prescriberorganizations": [],
            "user_institutions": [],
            "matomo_custom_variables": OrderedDict(
                [("is_authenticated", "yes"), ("account_type", None), ("account_sub_type", None)]
            ),
        }

    def test_siae_one_membership(self):
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        self.assertTrue(siae.has_admin(user))

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        middleware = SessionMiddleware()
        middleware.process_request(request)
        request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY] = siae.pk
        request.session.save()

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)
            expected = self.default_result | {
                "current_siae": siae,
                "user_siaes": [siae],
                "user_is_admin": True,
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

        siae3 = SiaeFactory()
        siae3.members.add(user)
        self.assertFalse(siae3.has_admin(user))

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        middleware = SessionMiddleware()
        middleware.process_request(request)
        request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY] = siae3.pk
        request.session.save()

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)
            expected = self.default_result | {
                "current_siae": siae3,
                "user_siaes": [siae1, siae2, siae3],
                "user_is_admin": False,
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

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        middleware = SessionMiddleware()
        middleware.process_request(request)
        request.session[settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY] = organization.pk
        request.session.save()

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)
            expected = self.default_result | {
                "current_prescriber_organization": organization,
                "user_prescriberorganizations": [organization],
                "user_is_admin": True,
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

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        middleware = SessionMiddleware()
        middleware.process_request(request)
        request.session[settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY] = organization1.pk
        request.session.save()

        with self.assertNumQueries(1):
            result = get_current_organization_and_perms(request)
            expected = self.default_result | {
                "current_prescriber_organization": organization1,
                "user_prescriberorganizations": [organization1, organization2],
                "user_is_admin": True,
                "matomo_custom_variables": OrderedDict(
                    [
                        ("is_authenticated", "yes"),
                        ("account_type", "prescriber"),
                        ("account_sub_type", "prescriber_with_unauthorized_org"),
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
        middleware = SessionMiddleware()
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
        middleware = SessionMiddleware()
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
        middleware = SessionMiddleware()
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
        middleware = SessionMiddleware()
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
        middleware = SessionMiddleware()
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
    @mock.patch(
        "itou.utils.apis.api_entreprise.EtablissementAPI.get", return_value=(ETABLISSEMENT_API_RESULT_MOCK, None)
    )
    def test_etablissement_api(self, mock_api_entreprise):
        etablissement = EtablissementAPI("26570134200148")

        self.assertEqual(etablissement.name, "CENTRE COMMUNAL D'ACTION SOCIALE")
        self.assertEqual(etablissement.address_line_1, "22 RUE DU WAD BILLY")
        self.assertEqual(etablissement.address_line_2, "22-24")
        self.assertEqual(etablissement.post_code, "57000")
        self.assertEqual(etablissement.city, "METZ")
        self.assertFalse(etablissement.is_closed)


class PoleEmploiTest(SimpleTestCase):
    @mock.patch(
        "itou.utils.apis.pole_emploi.PoleEmploiRechercheIndividuCertifieAPI.post",
        return_value=(POLE_EMPLOI_RECHERCHE_INDIVIDU_CERTIFIE_API_RESULT_KNOWN_MOCK, None),
    )
    def test_recherche_individu_certifie_api_nominal(self, mock_api_entreprise):
        individu = PoleEmploiRechercheIndividuCertifieAPI({}, "")

        self.assertTrue(individu.is_valid)
        self.assertEqual(individu.id_national_demandeur, "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ")
        self.assertEqual(individu.code_sortie, "S001")

    @mock.patch(
        "itou.utils.apis.pole_emploi.PoleEmploiRechercheIndividuCertifieAPI.post",
        return_value=(POLE_EMPLOI_RECHERCHE_INDIVIDU_CERTIFIE_API_RESULT_ERROR_MOCK, "Unable to fetch user data."),
    )
    def test_recherche_individu_certifie_api_error(self, mock_api_entreprise):
        individu = PoleEmploiRechercheIndividuCertifieAPI({}, "")

        self.assertFalse(individu.is_valid)


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
        for i in range(49):
            recipients.append(Faker("email", locale="fr_FR"))

        message = EmailMessage(from_email="unit-test@tests.com", body="", to=recipients)
        result = sanitize_mailjet_recipients(message)

        self.assertEqual(1, len(result))
        self.assertEqual(49, len(result[0].to))

    def test_must_split_emails(self):
        # 2 emails are needed; one with 50 the other with 25
        recipients = []
        for i in range(75):
            recipients.append(Faker("email", locale="fr_FR"))

        message = EmailMessage(from_email="unit-test@tests.com", body="", to=recipients)
        result = sanitize_mailjet_recipients(message)

        self.assertEqual(2, len(result))
        self.assertEqual(50, len(result[0].to))
        self.assertEqual(25, len(result[1].to))


class ResumeFormMixinTest(TestCase):
    def test_pole_emploi_internal_resume_link(self):
        resume_link = "http://ds000-xxxx-00xx000.xxx00.pole-emploi.intra/docnums/portfolio-usager/XXXXXXXXXXX/CV.pdf?Expires=1590485264&Signature=XXXXXXXXXXXXXXXX"  # noqa E501
        form = ResumeFormMixin(data={"resume_link": resume_link})
        self.assertFalse(form.is_valid())
        self.assertTrue(form.has_error("resume_link"))

    def test_valid_resume_link(self):
        resume_link = "https://www.moncv.fr/vive_moi.pdf"
        form = ResumeFormMixin(data={"resume_link": resume_link})
        self.assertTrue(form.is_valid())
        self.assertFalse(form.has_error("resume_link"))
