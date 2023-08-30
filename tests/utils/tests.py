import datetime
import decimal
import functools
import importlib
import json
import uuid

import faker
import pytest
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import AnonymousUser, Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import ValidationError
from django.core.mail.message import EmailMessage
from django.http import HttpResponse
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from factory import Faker
from faker import Faker as fk
from pytest_django.asserts import assertContains, assertNumQueries, assertRedirects

import itou.utils.json
import itou.utils.session
from itou.approvals.models import Suspension
from itou.job_applications.models import JobApplicationWorkflow
from itou.siaes.models import Siae, SiaeMembership
from itou.users.enums import KIND_JOB_SEEKER, KIND_PRESCRIBER, KIND_SIAE_STAFF, UserKind
from itou.users.models import User
from itou.utils import constants as global_constants, pagination
from itou.utils.emails import redact_email_address
from itou.utils.models import PkSupportRemark
from itou.utils.password_validation import CnilCompositionPasswordValidator
from itou.utils.perms.context_processors import get_current_organization_and_perms
from itou.utils.perms.middleware import ItouCurrentOrganizationMiddleware
from itou.utils.perms.user import get_user_info
from itou.utils.sync import DiffItem, DiffItemKind, yield_sync_diff
from itou.utils.tasks import sanitize_mailjet_recipients
from itou.utils.templatetags import dict_filters, format_filters, job_applications
from itou.utils.tokens import SIAE_SIGNUP_MAGIC_LINK_TIMEOUT, SiaeSignupTokenGenerator
from itou.utils.urls import (
    add_url_params,
    get_absolute_url,
    get_external_link_markup,
    get_safe_url,
    get_tally_form_url,
)
from itou.utils.validators import (
    alphanumeric,
    validate_af_number,
    validate_birthdate,
    validate_code_safir,
    validate_html,
    validate_naf,
    validate_nir,
    validate_pole_emploi_id,
    validate_post_code,
    validate_siren,
    validate_siret,
)
from tests.approvals.factories import SuspensionFactory
from tests.institutions.factories import (
    InstitutionFactory,
    InstitutionMembershipFactory,
    InstitutionWithMembershipFactory,
)
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationFactory, PrescriberOrganizationWithMembershipFactory
from tests.siaes.factories import SiaeFactory, SiaeMembershipFactory, SiaePendingGracePeriodFactory
from tests.users.factories import (
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    SiaeStaffFactory,
)
from tests.utils.test import TestCase, assertMessagesFromRequest, parse_response_to_soup


def get_response_for_middlewaremixin(request):
    """
    `SessionMiddleware` inherits from `MiddlewareMixin` which requires
    a `get_response` argument since Django 4.0:
    https://github.com/django/django/pull/11828

    An empty `HttpResponse` does the trick.
    """
    return HttpResponse()


@pytest.fixture
def mocked_get_response_for_middlewaremixin(mocker):
    return mocker.Mock(wraps=get_response_for_middlewaremixin)


class TestItouCurrentOrganizationMiddleware:
    def test_anonymous_user(self, mocked_get_response_for_middlewaremixin):
        factory = RequestFactory()
        request = factory.get("/")
        request.user = AnonymousUser()
        with assertNumQueries(0):
            ItouCurrentOrganizationMiddleware(mocked_get_response_for_middlewaremixin)(request)
        assert mocked_get_response_for_middlewaremixin.call_count == 1

    def test_job_seeker(self, mocked_get_response_for_middlewaremixin):
        factory = RequestFactory()
        request = factory.get("/")
        request.user = JobSeekerFactory()
        SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
        with assertNumQueries(0):
            ItouCurrentOrganizationMiddleware(mocked_get_response_for_middlewaremixin)(request)
        assert mocked_get_response_for_middlewaremixin.call_count == 1
        assert request.session.is_empty()

    def test_siae_member(self, mocked_get_response_for_middlewaremixin):
        factory = RequestFactory()
        request = factory.get("/")
        siae = SiaeMembershipFactory().siae
        request.user = siae.members.first()
        SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
        with assertNumQueries(
            # Retrieve user memberships
            1
            # Check if siaes are active or in grace period
            + 1
        ):
            ItouCurrentOrganizationMiddleware(mocked_get_response_for_middlewaremixin)(request)
        assert mocked_get_response_for_middlewaremixin.call_count == 1
        # Session updated
        assert request.session[global_constants.ITOU_SESSION_CURRENT_SIAE_KEY] == siae.pk

    def test_siae_no_member(self, mocked_get_response_for_middlewaremixin):
        factory = RequestFactory()
        request = factory.get("/")
        request.user = SiaeStaffFactory()
        SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
        MessageMiddleware(get_response_for_middlewaremixin).process_request(request)
        with assertNumQueries(1):  # Retrieve user memberships
            response = ItouCurrentOrganizationMiddleware(get_response_for_middlewaremixin)(request)
        assert mocked_get_response_for_middlewaremixin.call_count == 0
        assertRedirects(response, reverse("account_logout"), fetch_redirect_response=False)
        assertMessagesFromRequest(
            request,
            [
                (
                    "WARNING",
                    (
                        "Nous sommes désolés, votre compte n'est actuellement rattaché à aucune structure."
                        "<br>Nous espérons cependant avoir l'occasion de vous accueillir de nouveau."
                    ),
                )
            ],
        )
        # Session untouched
        assert request.session.is_empty()

    def test_siae_member_of_inactive_siae(self, mocked_get_response_for_middlewaremixin):
        factory = RequestFactory()
        request = factory.get("/")
        siae = SiaeMembershipFactory(siae__subject_to_eligibility=True, siae__convention=None).siae
        request.user = siae.members.first()
        SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
        MessageMiddleware(get_response_for_middlewaremixin).process_request(request)
        with assertNumQueries(
            # Retrieve user memberships
            1
            # Check if siaes are active or in grace period
            + 1
        ):
            response = ItouCurrentOrganizationMiddleware(mocked_get_response_for_middlewaremixin)(request)
        assert mocked_get_response_for_middlewaremixin.call_count == 0
        assertRedirects(response, reverse("account_logout"), fetch_redirect_response=False)
        assertMessagesFromRequest(
            request,
            [
                (
                    "WARNING",
                    (
                        "Nous sommes désolés, votre compte n'est malheureusement plus actif car la ou les "
                        "structures associées ne sont plus conventionnées. "
                        "Nous espérons cependant avoir l'occasion de vous accueillir de nouveau."
                    ),
                )
            ],
        )
        # Session untouched
        assert request.session.is_empty()

    def test_siae_member_of_siae_in_grace_period(self, mocked_get_response_for_middlewaremixin):
        factory = RequestFactory()
        request = factory.get("/")
        siae = SiaePendingGracePeriodFactory()
        request.user = SiaeMembershipFactory(siae=siae).user
        SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
        MessageMiddleware(get_response_for_middlewaremixin).process_request(request)
        with assertNumQueries(
            # Retrieve user memberships
            1
            # Check if siaes are active or in grace period
            + 1
        ):
            ItouCurrentOrganizationMiddleware(mocked_get_response_for_middlewaremixin)(request)
        assert mocked_get_response_for_middlewaremixin.call_count == 1
        # Session updated
        assert request.session[global_constants.ITOU_SESSION_CURRENT_SIAE_KEY] == siae.pk

    def test_siae_member_of_siae_in_grace_period_and_active_siae(self, mocked_get_response_for_middlewaremixin):
        factory = RequestFactory()
        request = factory.get("/")
        siae = SiaePendingGracePeriodFactory()
        request.user = SiaeMembershipFactory(siae=siae).user
        active_siae = SiaeMembershipFactory(user=request.user, siae__not_subject_to_eligibility=True).siae
        SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
        MessageMiddleware(get_response_for_middlewaremixin).process_request(request)
        with assertNumQueries(
            # Retrieve user memberships
            1
            # Check if siaes are active or in grace period
            + 1
        ):
            ItouCurrentOrganizationMiddleware(mocked_get_response_for_middlewaremixin)(request)
        assert mocked_get_response_for_middlewaremixin.call_count == 1
        # Session updated
        assert request.session[global_constants.ITOU_SESSION_CURRENT_SIAE_KEY] == active_siae.pk

    def test_prescriber_no_organization(self, mocked_get_response_for_middlewaremixin):
        factory = RequestFactory()
        request = factory.get("/")
        request.user = PrescriberFactory()
        SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
        with assertNumQueries(1):  # retrieve user memberships
            ItouCurrentOrganizationMiddleware(mocked_get_response_for_middlewaremixin)(request)
        assert mocked_get_response_for_middlewaremixin.call_count == 1
        # Session untouched
        assert request.session.is_empty()
        # Check new request attributes
        assert request.current_organization is None
        assert request.organizations == []
        assert not request.is_current_organization_admin

    def test_prescriber_with_organization(self, mocked_get_response_for_middlewaremixin):
        factory = RequestFactory()
        request = factory.get("/")
        organization = PrescriberOrganizationWithMembershipFactory()
        request.user = organization.members.first()
        SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
        with assertNumQueries(1):  # retrieve user memberships
            ItouCurrentOrganizationMiddleware(mocked_get_response_for_middlewaremixin)(request)
        assert mocked_get_response_for_middlewaremixin.call_count == 1
        # Session updated
        assert request.session[global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY] == organization.pk
        # Check new request attributes
        assert request.current_organization == organization
        assert request.organizations == [organization]
        assert request.is_current_organization_admin

    def test_prescriber_wrong_org_in_session(self, mocked_get_response_for_middlewaremixin):
        factory = RequestFactory()
        request = factory.get("/")
        request.user = PrescriberFactory()
        organization = PrescriberOrganizationFactory()
        SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
        request.session[global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY] = organization.pk
        request.session.save()
        with assertNumQueries(1):  # retrieve user memberships
            ItouCurrentOrganizationMiddleware(mocked_get_response_for_middlewaremixin)(request)
        assert mocked_get_response_for_middlewaremixin.call_count == 1
        # Session cleaned up
        assert request.session.get(global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY) is None
        # Check new request attributes
        assert request.current_organization is None
        assert request.organizations == []
        assert not request.is_current_organization_admin

    def test_labor_inspector_admin_member(self, mocked_get_response_for_middlewaremixin):
        factory = RequestFactory()
        request = factory.get("/")
        institution = InstitutionWithMembershipFactory()
        request.user = institution.members.first()
        SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
        with assertNumQueries(1):  # retrieve user memberships
            ItouCurrentOrganizationMiddleware(mocked_get_response_for_middlewaremixin)(request)
        assert mocked_get_response_for_middlewaremixin.call_count == 1
        # Session updated
        assert request.session[global_constants.ITOU_SESSION_CURRENT_INSTITUTION_KEY] == institution.pk
        # Check new request attributes
        assert request.current_organization == institution
        assert request.organizations == [institution]
        assert request.is_current_organization_admin

    def test_labor_inspector_member_of_2_institutions(self, mocked_get_response_for_middlewaremixin):
        factory = RequestFactory()
        request = factory.get("/")
        institution1 = InstitutionWithMembershipFactory()
        request.user = institution1.members.first()
        institution2 = InstitutionMembershipFactory(is_admin=False, user=request.user).institution
        SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
        request.session[global_constants.ITOU_SESSION_CURRENT_INSTITUTION_KEY] = institution2.pk
        request.session.save()
        with assertNumQueries(1):  # retrieve user memberships
            ItouCurrentOrganizationMiddleware(mocked_get_response_for_middlewaremixin)(request)
        assert mocked_get_response_for_middlewaremixin.call_count == 1
        # Session untouched
        assert request.session[global_constants.ITOU_SESSION_CURRENT_INSTITUTION_KEY] == institution2.pk
        # Check new request attributes
        assert request.current_organization == institution2
        assert request.organizations == [institution1, institution2]
        assert not request.is_current_organization_admin

    def test_labor_inspector_no_member(self, mocked_get_response_for_middlewaremixin):
        factory = RequestFactory()
        request = factory.get("/")
        request.user = LaborInspectorFactory()
        SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
        MessageMiddleware(get_response_for_middlewaremixin).process_request(request)
        with assertNumQueries(1):  # retrieve user memberships
            response = ItouCurrentOrganizationMiddleware(mocked_get_response_for_middlewaremixin)(request)
        assert mocked_get_response_for_middlewaremixin.call_count == 0
        assertRedirects(response, reverse("account_logout"), fetch_redirect_response=False)
        assertMessagesFromRequest(
            request,
            [
                (
                    "WARNING",
                    (
                        "Nous sommes désolés, votre compte n'est actuellement rattaché à aucune structure."
                        "<br>Nous espérons cependant avoir l'occasion de vous accueillir de nouveau."
                    ),
                )
            ],
        )
        # Session untouched
        assert request.session.is_empty()
        # Check new request attributes
        assert request.current_organization is None
        assert request.organizations == []
        assert not request.is_current_organization_admin


class ContextProcessorsGetCurrentOrganizationAndPermsTest(TestCase):
    def go_to_dashboard(self, user, establishment_session_key, establishment_pk):
        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        middleware = SessionMiddleware(get_response_for_middlewaremixin)
        middleware.process_request(request)
        request.session[establishment_session_key] = establishment_pk
        ItouCurrentOrganizationMiddleware(get_response_for_middlewaremixin)(request)
        request.session.save()
        return request

    def test_siae_one_membership(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        assert siae.has_admin(user)

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=global_constants.ITOU_SESSION_CURRENT_SIAE_KEY,
            establishment_pk=siae.pk,
        )

        with self.assertNumQueries(0):
            result = get_current_organization_and_perms(request)
            assert result == {
                "current_siae": siae,
                "user_is_siae_admin": True,
                "user_siaes": [siae],
            }

    def test_siae_multiple_memberships(self):
        # Specify name to ensure alphabetical sorting order.
        siae1 = SiaeFactory(name="1", with_membership=True)
        user = siae1.members.first()
        assert siae1.has_admin(user)

        siae2 = SiaeFactory(name="2")
        siae2.members.add(user)
        assert not siae2.has_admin(user)

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=global_constants.ITOU_SESSION_CURRENT_SIAE_KEY,
            establishment_pk=siae2.pk,
        )

        with self.assertNumQueries(0):
            result = get_current_organization_and_perms(request)
            assert result == {
                "current_siae": siae2,
                "user_is_siae_admin": False,
                "user_siaes": [siae1, siae2],
            }

    def test_prescriber_organization_one_membership(self):
        organization = PrescriberOrganizationWithMembershipFactory()
        user = organization.members.first()
        assert user.prescribermembership_set.get(organization=organization).is_admin

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY,
            establishment_pk=organization.pk,
        )

        with self.assertNumQueries(0):
            result = get_current_organization_and_perms(request)
            assert result == {
                "current_prescriber_organization": organization,
                "user_prescriberorganizations": [organization],
                "user_is_prescriber_org_admin": True,
            }

    def test_prescriber_organization_multiple_membership(self):
        # Specify name to ensure alphabetical sorting order.
        organization1 = PrescriberOrganizationWithMembershipFactory(name="1")
        user = organization1.members.first()
        assert user.prescribermembership_set.get(organization=organization1).is_admin

        organization2 = PrescriberOrganizationWithMembershipFactory(name="2")
        organization2.members.add(user)

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY,
            establishment_pk=organization1.pk,
        )

        with self.assertNumQueries(0):
            result = get_current_organization_and_perms(request)
            assert result == {
                "current_prescriber_organization": organization1,
                "user_prescriberorganizations": [organization1, organization2],
                "user_is_prescriber_org_admin": True,
            }

    def test_labor_inspector_one_institution(self):
        institution = InstitutionWithMembershipFactory()
        user = institution.members.first()
        assert user.institutionmembership_set.get(institution=institution).is_admin

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=global_constants.ITOU_SESSION_CURRENT_INSTITUTION_KEY,
            establishment_pk=institution.pk,
        )

        with self.assertNumQueries(0):
            result = get_current_organization_and_perms(request)
            assert result == {
                "current_institution": institution,
                "user_institutions": [institution],
                "user_is_institution_admin": True,
            }

    def test_labor_inspector_multiple_institutions(self):
        # Specify name to ensure alphabetical sorting order.
        institution1 = InstitutionWithMembershipFactory(name="1")
        user = institution1.members.first()
        assert user.institutionmembership_set.get(institution=institution1).is_admin
        institution2 = InstitutionFactory(name="2")
        institution2.members.add(user)
        assert not institution2.has_admin(user)

        request = self.go_to_dashboard(
            user=user,
            establishment_session_key=global_constants.ITOU_SESSION_CURRENT_INSTITUTION_KEY,
            establishment_pk=institution2.pk,
        )

        with self.assertNumQueries(0):
            result = get_current_organization_and_perms(request)
            assert result == {
                "current_institution": institution2,
                "user_institutions": [institution1, institution2],
                "user_is_institution_admin": False,
            }


def test_logout_as_siae_multiple_memberships(client):
    siae1 = SiaeFactory(name="1st siae", with_membership=True)
    user = siae1.members.first()
    assert siae1.has_admin(user)

    siae2 = SiaeFactory(name="2nd siae")
    siae2.members.add(user)
    assert not siae2.has_admin(user)

    client.force_login(user)
    # Select the 1st SIAE as current one
    session = client.session
    session[global_constants.ITOU_SESSION_CURRENT_SIAE_KEY] = siae1.pk
    session.save()

    response = client.get(reverse("account_logout"))
    # assert client.session.get(global_constants.ITOU_SESSION_CURRENT_SIAE_KEY) == siae1.pk
    # The dropdown to switch to the 2nd SIAE is available on logout screen
    assertContains(response, siae2.name)


def test_logout_as_labor_inspector_multiple_institutions(client):
    institution1 = InstitutionWithMembershipFactory(name="1st institution")
    user = institution1.members.first()
    institution2 = InstitutionFactory(name="2nd institution")
    institution2.members.add(user)

    client.force_login(user)
    # Select the 1st institution as current
    session = client.session
    session[global_constants.ITOU_SESSION_CURRENT_INSTITUTION_KEY] = institution1.pk
    session.save()

    response = client.get(reverse("account_logout"))
    # The dropdown to switch to the 2nd SIAE is available on logout screen
    assertContains(response, institution2.name)


class UtilsValidatorsTest(TestCase):
    def test_validate_alphanumeric(self):
        with pytest.raises(ValidationError):
            alphanumeric("1245a_89871")
        alphanumeric("6201Z")

    def test_validate_code_safir(self):
        with pytest.raises(ValidationError):
            validate_code_safir("1a3v5")
        with pytest.raises(ValidationError):
            validate_code_safir("123456")
        alphanumeric("12345")

    def test_validate_naf(self):
        with pytest.raises(ValidationError):
            validate_naf("1")
        with pytest.raises(ValidationError):
            validate_naf("12254")
        with pytest.raises(ValidationError):
            validate_naf("abcde")
        with pytest.raises(ValidationError):
            validate_naf("1245789871")
        validate_naf("6201Z")

    def test_validate_siren(self):
        with pytest.raises(ValidationError):
            validate_siren("12000015")
        with pytest.raises(ValidationError):
            validate_siren("1200001531")
        with pytest.raises(ValidationError):
            validate_siren("12000015a")
        with pytest.raises(ValidationError):
            validate_siren("azertyqwe")
        validate_siren("120000153")

    def test_validate_siret(self):
        with pytest.raises(ValidationError):
            validate_siret("1200001530001")
        with pytest.raises(ValidationError):
            validate_siret("120000153000111")
        with pytest.raises(ValidationError):
            validate_siret("1200001530001a")
        with pytest.raises(ValidationError):
            validate_siret("azertyqwerty")
        validate_siret("12000015300011")

    def test_validate_post_code(self):
        with pytest.raises(ValidationError):
            validate_post_code("")
        with pytest.raises(ValidationError):
            validate_post_code("1234")
        with pytest.raises(ValidationError):
            validate_post_code("123456")
        with pytest.raises(ValidationError):
            validate_post_code("1234X")
        validate_post_code("12345")

    def test_validate_pole_emploi_id(self):
        with pytest.raises(ValidationError):
            validate_pole_emploi_id("A2345678")
        with pytest.raises(ValidationError):
            validate_pole_emploi_id("1234")
        with pytest.raises(ValidationError):
            validate_pole_emploi_id("123412345654")
        with pytest.raises(ValidationError):
            validate_pole_emploi_id("A234567É")
        validate_pole_emploi_id("12345678")
        validate_pole_emploi_id("1234567E")

    def test_validate_birthdate(self):
        # Min.
        with pytest.raises(ValidationError):
            validate_birthdate(datetime.date(1899, 12, 31))
        validate_birthdate(datetime.date(1900, 1, 1))
        # Max.
        max_date = timezone.localdate() - relativedelta(years=16)
        with pytest.raises(ValidationError):
            validate_birthdate(max_date + datetime.timedelta(days=1))
        with pytest.raises(ValidationError):
            validate_birthdate(max_date + datetime.timedelta(days=365))
        with pytest.raises(ValidationError):
            validate_birthdate(max_date)
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
        with pytest.raises(ValidationError):
            validate_nir("123456789")
        with pytest.raises(ValidationError):
            validate_nir("141068078200557123")
        # Should start with 1 or 2.
        with pytest.raises(ValidationError):
            validate_nir("341208078200557")
        # Third group should be between 0 and 12.
        with pytest.raises(ValidationError):
            validate_nir("141208078200557")
        # Last group should validate the first 13 characters.
        with pytest.raises(ValidationError):
            validate_nir("141068078200520")

    def test_validate_af_number(self):
        # Dubious values.
        with pytest.raises(ValidationError):
            validate_af_number("")
        with pytest.raises(ValidationError):
            validate_af_number(None)

        # Missing or incorrect suffix (should be A0M0 or alike).
        with pytest.raises(ValidationError):
            validate_af_number("ACI063170007")
        with pytest.raises(ValidationError):
            validate_af_number("ACI063170007Z1Z1")

        # Missing digit.
        with pytest.raises(ValidationError):
            validate_af_number("EI08018002A1M1")
        with pytest.raises(ValidationError):
            validate_af_number("AI08816001A1M1")

        # Correct values.
        validate_af_number("ACI063170007A0M0")
        validate_af_number("ACI063170007A0M1")
        validate_af_number("ACI063170007A1M1")
        validate_af_number("EI080180002A1M1")
        validate_af_number("EI59V182019A1M1")
        validate_af_number("AI088160001A1M1")
        validate_af_number("ETTI080180002A1M1")
        validate_af_number("ETTI59L181001A1M1")

    def test_validate_html(self):
        validate_html("<h1>I'm valid!</h1>")
        with pytest.raises(ValidationError):
            validate_html("<div>Oops! Someone forgot to close me...")

        with pytest.raises(ValidationError):
            validate_html("<script>$('.green');</script>")


class UtilsTemplateTagsTestCase(TestCase):
    def test_url_add_query(self):
        """Test `url_add_query` template tag."""

        base_url = "https://emplois.inclusion.beta.gouv.fr"
        # Full URL.
        context = {"url": f"{base_url}/siae/search?distance=100&city=aubervilliers-93&page=55&page=1"}
        template = Template("{% load url_add_query %}{% url_add_query url page=2 %}")
        out = template.render(Context(context))
        expected = f"{base_url}/siae/search?distance=100&amp;city=aubervilliers-93&amp;page=2"
        assert out == expected

        # Relative URL.
        context = {"url": "/siae/search?distance=50&city=metz-57"}
        template = Template("{% load url_add_query %}{% url_add_query url page=22 %}")
        out = template.render(Context(context))
        expected = "/siae/search?distance=50&amp;city=metz-57&amp;page=22"
        assert out == expected

        # Empty URL.
        context = {"url": ""}
        template = Template("{% load url_add_query %}{% url_add_query url page=1 %}")
        out = template.render(Context(context))
        expected = "?page=1"
        assert out == expected

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
        assert out == expected

        # No redirection value.
        template = Template(
            """
            {% load redirection_fields %}
            {% url "dashboard:index" %}{% redirection_url name=redirect_field_name value=redirect_field_value %}
        """
        )
        out = template.render(Context()).strip()
        expected = base_url
        assert out == expected

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
        assert out == expected

        # No redirection expected.
        template = Template(
            """
            {% load redirection_fields %}
            {% redirection_input_field name=redirect_field_name value=redirect_field_value %}
        """
        )
        out = template.render(Context()).strip()
        expected = ""
        assert out == expected

    def test_call_method(self):
        """Test `call_method` template tag."""
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        context = {"siae": siae, "user": user}
        template = Template("{% load call_method %}{% call_method siae 'has_member' user %}")
        out = template.render(Context(context))
        expected = "True"
        assert out == expected

    def test_pluralizefr(self):
        """Test `pluralizefr` template tag."""
        template = Template("{% load str_filters %}résultat{{ counter|pluralizefr }}")
        out = template.render(Context({"counter": 0}))
        assert out == "résultat"
        out = template.render(Context({"counter": 1}))
        assert out == "résultat"
        out = template.render(Context({"counter": 10}))
        assert out == "résultats"

    def test_mask_unless(self):
        template = Template("""{% load str_filters %}{{ value|mask_unless:predicate }}""")

        assert template.render(Context({"value": "Firstname Lastname", "predicate": True})) == "Firstname Lastname"
        assert template.render(Context({"value": "Firstname Lastname", "predicate": False})) == "F… L…"
        assert template.render(Context({"value": "Firstname Middlename Lastname", "predicate": False})) == "F… M… L…"
        assert (
            template.render(Context({"value": "Firstname Middlename Lastname1-Lastname2", "predicate": False}))
            == "F… M… L…"
        )
        assert (
            template.render(Context({"value": " Firstname  Middlename   Lastname ", "predicate": False})) == "F… M… L…"
        )
        assert (
            template.render(Context({"value": "\tFirstname\t\tMiddlename\tLastname\t\t", "predicate": False}))
            == "F… M… L…"
        )

    @override_settings(TALLY_URL="https://foobar")
    def test_tally_url_custom_template_tag(self):
        test_id = 1234
        context = {
            "test_id": test_id,
        }
        template = Template("{% load tally %}url:{% tally_form_url 'abcde' pk=test_id hard='coded'%}")
        out = template.render(Context(context))

        assert f"url:{get_tally_form_url('abcde', pk=test_id, hard='coded')}" == out


class UtilsTemplateFiltersTestCase(TestCase):
    def test_format_phone(self):
        """Test `format_phone` template filter."""
        assert format_filters.format_phone("") == ""
        assert format_filters.format_phone("0102030405") == "01 02 03 04 05"

    def test_get_dict_item(self):
        """Test `get_dict_item` template filter."""
        my_dict = {"key1": "value1", "key2": "value2"}
        assert dict_filters.get_dict_item(my_dict, "key1") == "value1"
        assert dict_filters.get_dict_item(my_dict, "key2") == "value2"

    def test_format_siret(self):
        # Don't format invalid SIRET
        assert format_filters.format_siret("1234") == "1234"
        assert format_filters.format_siret(None) == "None"
        # SIREN
        assert format_filters.format_siret("123456789") == "123 456 789"
        # SIRET
        assert format_filters.format_siret("12345678912345") == "123 456 789 12345"

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
                assert format_filters.format_nir(nir) == expected

    def test_format_approval_number(self):
        test_cases = [
            ("", ""),
            ("XXXXX3500001", '<span>XXXXX</span><span class="ml-1">35</span><span class="ml-1">00001</span>'),
            # Actual formatting does not really matter, just verify it does not crash.
            ("foo", '<span>foo</span><span class="ml-1"></span><span class="ml-1"></span>'),
        ]
        for number, expected in test_cases:
            with self.subTest(number):
                assert format_filters.format_approval_number(number) == expected


class UtilsUrlsTestCase(TestCase):
    def test_add_url_params(self):
        """Test `urls.add_url_params()`."""

        base_url = "http://localhost/test?next=/siae/search%3Fdistance%3D100%26city%3Dstrasbourg-67"

        url_test = add_url_params(base_url, {"test": "value"})
        assert (
            url_test
            == "http://localhost/test?next=%2Fsiae%2Fsearch%3Fdistance%3D100%26city%3Dstrasbourg-67&test=value"
        )

        url_test = add_url_params(base_url, {"mypath": "%2Fvalue%2Fpath"})

        assert url_test == (
            "http://localhost/test?next=%2Fsiae%2Fsearch%3Fdistance%3D100%26city%3Dstrasbourg-67"
            "&mypath=%252Fvalue%252Fpath"
        )

        url_test = add_url_params(base_url, {"mypath": None})

        assert url_test == "http://localhost/test?next=%2Fsiae%2Fsearch%3Fdistance%3D100%26city%3Dstrasbourg-67"

        url_test = add_url_params(base_url, {"mypath": ""})

        assert (
            url_test == "http://localhost/test?next=%2Fsiae%2Fsearch%3Fdistance%3D100%26city%3Dstrasbourg-67&mypath="
        )

    def test_get_safe_url(self):
        """Test `urls.get_safe_url()`."""

        request = RequestFactory().get("/?next=/siae/search%3Fdistance%3D100%26city%3Dstrasbourg-67")
        url = get_safe_url(request, "next")
        expected = "/siae/search?distance=100&city=strasbourg-67"
        assert url == expected

        request = RequestFactory().post("/", data={"next": "/siae/search?distance=100&city=strasbourg-67"})
        url = get_safe_url(request, "next")
        expected = "/siae/search?distance=100&city=strasbourg-67"
        assert url == expected

        request = RequestFactory().get("/?next=https://evil.com/siae/search")
        url = get_safe_url(request, "next")
        expected = None
        assert url == expected

        request = RequestFactory().post("/", data={"next": "https://evil.com"})
        url = get_safe_url(request, "next", fallback_url="/fallback")
        expected = "/fallback"
        assert url == expected

    def test_get_absolute_url(self):
        url = get_absolute_url()
        assert f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}/" == url

        # With path
        path = "awesome/team/"
        url = get_absolute_url(path)
        assert f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}/{path}" == url

        # Escape first slash
        path = "/awesome/team/"
        url = get_absolute_url(path)
        assert f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}/awesome/team/" == url

    def test_get_external_link_markup(self):
        url = "https://emplois.inclusion.beta.gouv.fr"
        text = "Lien vers une ressource externe"
        expected = (
            f'<a href="{url}" rel="noopener" target="_blank" aria-label="Ouverture dans un nouvel onglet">{text}</a>'
        )
        assert get_external_link_markup(url=url, text=text) == expected


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
        assert user_info.user == user
        assert user_info.kind == KIND_SIAE_STAFF
        assert user_info.prescriber_organization is None
        assert user_info.is_authorized_prescriber is False
        assert user_info.siae == siae

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
        assert user_info.user == user
        assert user_info.kind == KIND_PRESCRIBER
        assert user_info.prescriber_organization == prescriber_organization
        assert user_info.is_authorized_prescriber is False
        assert user_info.siae is None

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
        assert user_info.user == user
        assert user_info.kind == KIND_PRESCRIBER
        assert user_info.prescriber_organization == prescriber_organization
        assert user_info.is_authorized_prescriber is True
        assert user_info.siae is None

    def test_get_user_info_for_prescriber_without_organisation(self):
        user = PrescriberFactory()

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        middleware = SessionMiddleware(get_response_for_middlewaremixin)
        middleware.process_request(request)
        request.session.save()

        user_info = get_user_info(request)
        assert user_info.user == user
        assert user_info.kind == KIND_PRESCRIBER
        assert user_info.prescriber_organization is None
        assert user_info.is_authorized_prescriber is False
        assert user_info.siae is None

    def test_get_user_info_for_job_seeker(self):
        user = JobSeekerFactory()

        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        middleware = SessionMiddleware(get_response_for_middlewaremixin)
        middleware.process_request(request)
        request.session.save()

        user_info = get_user_info(request)
        assert user_info.user == user
        assert user_info.kind == KIND_JOB_SEEKER
        assert user_info.prescriber_organization is None
        assert user_info.is_authorized_prescriber is False
        assert user_info.siae is None


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
        assert p0.check_token(siae, tk1) is True

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
        assert tk1 == tk2

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
        assert p1.check_token(siae, tk1) is True
        p2 = MockedSiaeSignupTokenGenerator(
            datetime.datetime.now() + datetime.timedelta(seconds=(SIAE_SIGNUP_MAGIC_LINK_TIMEOUT + 1))
        )
        assert p2.check_token(siae, tk1) is False

    def test_check_token_with_nonexistent_token_and_user(self):
        siae = Siae.objects.create()
        p0 = SiaeSignupTokenGenerator()
        tk1 = p0.make_token(siae)
        assert p0.check_token(None, tk1) is False
        assert p0.check_token(siae, None) is False
        assert p0.check_token(siae, tk1) is True

    def test_any_new_signup_invalidates_past_token(self):
        """
        Tokens are based on siae.members.count() so that
        any new signup invalidates past tokens.
        """
        siae = Siae.objects.create()
        p0 = SiaeSignupTokenGenerator()
        tk1 = p0.make_token(siae)
        assert p0.check_token(siae, tk1) is True
        user = User(kind=UserKind.SIAE_STAFF)
        user.save()
        membership = SiaeMembership()
        membership.user = user
        membership.siae = siae
        membership.save()
        assert p0.check_token(siae, tk1) is False


class CnilCompositionPasswordValidatorTest(SimpleTestCase):
    def test_validate(self):
        # Good passwords.

        # lower + upper + special char
        assert CnilCompositionPasswordValidator().validate("!*pAssWOrD") is None
        # lower + upper + digit
        assert CnilCompositionPasswordValidator().validate("MYp4ssW0rD") is None
        # lower + upper + digit + special char
        assert CnilCompositionPasswordValidator().validate("M+p4ssW0rD") is None

        # Wrong passwords.

        expected_error = CnilCompositionPasswordValidator.HELP_MSG

        with pytest.raises(ValidationError) as error:
            # Only lower + upper
            CnilCompositionPasswordValidator().validate("MYpAssWOrD")
        assert error.value.messages == [expected_error]
        assert error.value.error_list[0].code == "cnil_composition"

        with pytest.raises(ValidationError) as error:
            # Only lower + digit
            CnilCompositionPasswordValidator().validate("myp4ssw0rd")
        assert error.value.messages == [expected_error]
        assert error.value.error_list[0].code == "cnil_composition"

    def test_help_text(self):
        assert CnilCompositionPasswordValidator().get_help_text() == CnilCompositionPasswordValidator.HELP_MSG


class UtilsEmailsSplitRecipientTest(TestCase):
    """
    Test behavior of email backend when sending emails with more than 50 recipients
    (Mailjet API Limit)
    """

    def test_email_copy(self):
        fake_email = Faker("email", locale="fr_FR")
        message = EmailMessage(from_email="unit-test@tests.com", body="xxx", to=[fake_email], subject="test")
        result = sanitize_mailjet_recipients(message)

        assert 1 == len(result)

        assert "xxx" == result[0].body
        assert "unit-test@tests.com" == result[0].from_email
        assert fake_email == result[0].to[0]
        assert "test" == result[0].subject

    def test_dont_split_emails(self):
        recipients = []
        # Only one email is needed
        for _ in range(49):
            recipients.append(Faker("email", locale="fr_FR"))

        message = EmailMessage(from_email="unit-test@tests.com", body="", to=recipients)
        result = sanitize_mailjet_recipients(message)

        assert 1 == len(result)
        assert 49 == len(result[0].to)

    def test_must_split_emails(self):
        # 2 emails are needed; one with 50 the other with 25
        recipients = []
        for _ in range(75):
            recipients.append(Faker("email", locale="fr_FR"))

        message = EmailMessage(from_email="unit-test@tests.com", body="", to=recipients)
        result = sanitize_mailjet_recipients(message)

        assert 2 == len(result)
        assert 50 == len(result[0].to)
        assert 25 == len(result[1].to)


class SupportRemarkAdminViewsTest(TestCase):
    def test_add_support_remark_to_suspension(self):
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
        user = PrescriberFactory()
        self.client.force_login(user)
        response = self.client.get(url)
        assert response.status_code == 302

        # Add needed perms
        user = ItouStaffFactory()
        self.client.force_login(user)
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
        assert response.status_code == 200

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
        assert remark.remark == fake_remark

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
            assert "unknown" not in ns
            assert repr(ns) == f"<SessionNamespace({value_to_test!r})>"

        for value_to_test in [{"value": "42"}, ["value"], ("value",), {"value"}]:
            session[ns_name] = value_to_test
            assert "value" in ns
            assert repr(ns) == f"<SessionNamespace({value_to_test!r})>"

    def test_api_method(self):
        session = self._get_session_store()
        ns_name = faker.Faker().word()

        ns = itou.utils.session.SessionNamespace(session, ns_name)
        assert ns_name not in session  # The namespace doesn't yet exist in the session

        # .init()
        ns.init({"key": "value"})
        assert ns_name in session
        assert session[ns_name] == {"key": "value"}

        # .get()
        assert ns.get("key") == "value"
        assert ns.get("not_existing_key", None) is None
        assert ns.get("not_existing_key") is ns.NOT_SET
        assert not ns.get("not_existing_key")

        # .set()
        ns.set("key2", "value2")
        assert ns.get("key2") == "value2"
        assert session[ns_name] == {"key": "value", "key2": "value2"}

        # .update()
        ns.update({"key3": "value3"})
        assert ns.get("key3") == "value3"
        assert session[ns_name] == {"key": "value", "key2": "value2", "key3": "value3"}

        ns.update({"key": "other_value"})
        assert ns.get("key") == "other_value"
        assert session[ns_name] == {"key": "other_value", "key2": "value2", "key3": "value3"}

        # .as_dict()
        assert ns.as_dict() == {"key": "other_value", "key2": "value2", "key3": "value3"}

        # .exists() + .delete()
        assert ns.exists()
        ns.delete()
        assert ns_name not in session
        assert not ns.exists()

    def test_class_method(self):
        session = self._get_session_store()

        # .create_temporary()
        ns = itou.utils.session.SessionNamespace.create_temporary(session)
        assert isinstance(ns, itou.utils.session.SessionNamespace)
        assert str(uuid.UUID(ns.name)) == ns.name
        assert ns.name not in session  # .init() wasn't called


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
            datetime.datetime(2001, 1, 1, tzinfo=datetime.UTC),
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
            assert dumps(obj) == expected

        for obj, expected, *_ in self.ASYMMETRIC_CONVERSION:
            assert dumps(obj) == expected

        model_object = JobSeekerFactory()
        assert dumps(model_object) == str(model_object.pk)

    def test_decode(self):
        loads = functools.partial(json.loads, cls=itou.utils.json.JSONDecoder)

        for expected, s in self.SYMMETRIC_CONVERSION:
            assert loads(s) == expected

        for *_, s, expected in self.ASYMMETRIC_CONVERSION:
            assert loads(s) == expected


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


def test_yield_sync_diff():
    # NOTE(vperron): not ideal, since I'm using models from a different Django app.
    # But I'm not sure that for such a simple utility function, I should really create a model
    # dedicated to it in the tests... at least lazy import it to avoid circular imports for the
    # longest possible time. Also choose a very simple model.
    from itou.jobs.models import Rome

    # test trivial case
    items = list(
        yield_sync_diff(
            [],
            "key",
            Rome.objects.all(),
            "code",
            [("label", "name")],
        )
    )
    assert items == [
        DiffItem(
            key=None,
            kind=DiffItemKind.SUMMARY,
            label="count=0 label=Rome had the same key in collection and " "queryset",
            raw=None,
            db_obj=None,
        ),
        DiffItem(
            key=None, kind=DiffItemKind.SUMMARY, label="count=0 label=Rome added by collection", raw=None, db_obj=None
        ),
        DiffItem(
            key=None,
            kind=DiffItemKind.SUMMARY,
            label="count=0 label=Rome removed by collection",
            raw=None,
            db_obj=None,
        ),
    ]

    first_rome = Rome(code="FOO", name="Petit papa noel")
    first_rome.save()
    Rome(code="BAR", name="contenu inchangé").save()
    item_to_remove = Rome(code="BAZ", name="Vas-y francky")
    item_to_remove.save()
    items = list(
        yield_sync_diff(
            [
                {"key": "HELLO", "label": "nouvel objet stylé !"},
                {"key": "BAR", "label": "contenu inchangé"},
                {"key": "FOO", "label": "quand tu descendras du ciel..."},
            ],
            "key",
            Rome.objects.all(),
            "code",
            [("label", "name")],
        )
    )
    assert [d.kind for d in items] == [
        DiffItemKind.SUMMARY,
        DiffItemKind.EDITION,
        DiffItemKind.SUMMARY,
        DiffItemKind.ADDITION,
        DiffItemKind.SUMMARY,
        DiffItemKind.DELETION,
    ]
    assert [d.label for d in items] == [
        "count=2 label=Rome had the same key in collection and queryset",
        # only one item actually changed
        "\tCHANGED name=Petit papa noel changed to value=quand tu descendras du ciel...",
        "count=1 label=Rome added by collection",
        '\tADDED {"key": "HELLO", "label": "nouvel objet stylé !"}',
        "count=1 label=Rome removed by collection",
        "\tREMOVED Vas-y francky (BAZ)",
    ]
    assert [d.key for d in items] == [None, "FOO", None, "HELLO", None, "BAZ"]
    assert [d.raw for d in items] == [
        None,
        {"key": "FOO", "label": "quand tu descendras du ciel..."},
        None,
        {"key": "HELLO", "label": "nouvel objet stylé !"},
        None,
        None,
    ]
    assert [d.db_obj for d in items] == [None, first_rome, None, None, None, item_to_remove]

    # check lambda and detailed keys
    lines = [
        diff_item.label
        for diff_item in yield_sync_diff(
            [
                {"key": "HELLO", "label": "nouvel objet stylé !"},
                {"key": "BAR", "label": "contenu inchangé"},
                {"key": "FOO", "label": "quand tu descendras du ciel..."},
            ],
            "key",
            Rome.objects.all(),
            "code",
            [],  # no compared detailed keys
        )
    ]
    assert lines == [
        "count=2 label=Rome had the same key in collection and queryset",
        # in this mode we get a line for every item having the same ID, even if the content did not change
        "\tCHANGED item key=BAR",
        "\tCHANGED item key=FOO",
        "count=1 label=Rome added by collection",
        '\tADDED {"key": "HELLO", "label": "nouvel objet stylé !"}',
        "count=1 label=Rome removed by collection",
        "\tREMOVED Vas-y francky (BAZ)",
    ]


@pytest.mark.parametrize(
    "email,expected",
    [
        ("", ""),
        ("test", "t***"),
        ("test@localhost", "t***@l********"),
        ("test@example.com", "t***@e******.c**"),
        ("test.foo@example.com", "t*******@e******.c**"),
        ("test@beta.gouv.fr", "t***@b********.f*"),
    ],
)
def test_redact_email_adresse(email, expected):
    assert redact_email_address(email) == expected


def test_matomo_context_processor(client, settings, snapshot):
    """Test on a canically problematic view that we get the right Matomo properties.

    Namely, verify that the URL params are cleaned, sorted, the title is forced, and
    the path params are replaced by a the variadic version.

    Also ensure the user ID is correctly set.
    """
    settings.MATOMO_BASE_URL = "https://fake.matomo.url"
    siae = SiaeFactory(with_membership=True, membership__user__pk=99999)
    user = siae.members.first()
    client.force_login(user)

    # check that we don't crash when the route is not resolved
    response = client.get("/doesnotexist?token=blah&mtm_foo=truc")
    assert response.status_code == 404
    assert response.context["matomo_custom_url"] == "/doesnotexist?mtm_foo=truc"
    script_content = parse_response_to_soup(response, selector="#matomo-custom-init")
    assert str(script_content) == snapshot(name="matomo custom init 404")

    # canonical case
    url = reverse("siaes_views:card", kwargs={"siae_id": siae.pk})
    response = client.get(f"{url}?foo=bar&mtm_foo=truc&mtm_bar=bidule&city=paris")
    assert response.status_code == 200
    assert response.context["siae"] == siae
    assert response.context["matomo_custom_url"] == "siae/<int:siae_id>/card?city=paris&mtm_bar=bidule&mtm_foo=truc"
    assert response.context["matomo_custom_title"] == "Fiche de la structure d'insertion"
    assert response.context["matomo_user_id"] == user.pk
    script_content = parse_response_to_soup(response, selector="#matomo-custom-init")
    assert str(script_content) == snapshot(name="matomo custom init siae card")


@pytest.mark.parametrize("state", [s[0] for s in JobApplicationWorkflow.STATE_CHOICES])
def test_job_application_state_badge_processing(state, snapshot):
    job_application = JobApplicationFactory(id="00000000-0000-0000-0000-000000000000", state=state)
    assert job_applications.state_badge(job_application) == snapshot


def test_job_application_state_badge_oob_swap(snapshot):
    job_application = JobApplicationFactory(id="00000000-0000-0000-0000-000000000000")
    assert job_applications.state_badge(job_application, hx_swap_oob=True) == snapshot
