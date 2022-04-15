import dataclasses
import datetime
from unittest import mock
from urllib import parse

import httpx
import respx
from django.conf import settings
from django.contrib import auth
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from itou.prescribers.factories import PrescriberOrganizationFactory, PrescriberPoleEmploiFactory
from itou.prescribers.models import PrescriberOrganization

from ..users import enums as users_enums
from ..users.factories import DEFAULT_PASSWORD, PrescriberFactory, SiaeStaffFactory, UserFactory
from ..users.models import User
from .constants import (
    INCLUSION_CONNECT_ENDPOINT_AUTHORIZE,
    INCLUSION_CONNECT_ENDPOINT_LOGOUT,
    INCLUSION_CONNECT_ENDPOINT_TOKEN,
    INCLUSION_CONNECT_ENDPOINT_USERINFO,
    INCLUSION_CONNECT_SESSION_STATE,
    INCLUSION_CONNECT_SESSION_TOKEN,
    INCLUSION_CONNECT_STATE_EXPIRATION,
    PROVIDER_INCLUSION_CONNECT,
)
from .models import InclusionConnectState, InclusionConnectUserData, create_or_update_user, userinfo_to_user_model_dict
from .views import state_is_valid, state_new


INCLUSION_CONNECT_USERINFO = {
    "given_name": "Michel",
    "family_name": "AUDIARD",
    "email": "michel@lestontons.fr",
    "sub": "af6b26f9-85cd-484e-beb9-bea5be13e30f",  # username
}


# Make sure this decorator is before test definition, not here.
# @respx.mock
def _oauth_dance(test_class, email=None, assert_redirects=True):
    # User is logged out from IC when an error happens during the oauth dance.
    respx.get(INCLUSION_CONNECT_ENDPOINT_LOGOUT).respond(302)
    user_info = INCLUSION_CONNECT_USERINFO.copy()
    token_json = {"access_token": "7890123", "token_type": "Bearer", "expires_in": 60, "id_token": "123456"}
    respx.post(INCLUSION_CONNECT_ENDPOINT_TOKEN).mock(return_value=httpx.Response(200, json=token_json))

    if email:
        user_info["email"] = email

    respx.get(INCLUSION_CONNECT_ENDPOINT_USERINFO).mock(return_value=httpx.Response(200, json=user_info))

    csrf_signed = state_new()
    url = reverse("inclusion_connect:callback")
    response = test_class.client.get(url, data={"code": "123", "state": csrf_signed})
    if assert_redirects:
        test_class.assertRedirects(response, reverse("welcoming_tour:index"))

    return response


def _logout_from_IC(test_class, redirect_url=None, follow=False):
    respx.get(INCLUSION_CONNECT_ENDPOINT_LOGOUT).respond(302)
    params = {
        INCLUSION_CONNECT_SESSION_TOKEN: test_class.client.session.get(INCLUSION_CONNECT_SESSION_TOKEN),
        INCLUSION_CONNECT_SESSION_STATE: test_class.client.session.get(INCLUSION_CONNECT_SESSION_STATE),
    }
    if redirect_url:
        params["redirect_url"] = redirect_url

    logout_url = f"{reverse('inclusion_connect:logout')}?{urlencode(params)}"

    return test_class.client.get(logout_url, follow=follow)


class InclusionConnectModelTest(TestCase):
    # Same as france_connect.tests.FranceConnectTest.test_state_delete
    def test_state_delete(self):
        state = InclusionConnectState.objects.create(csrf="foo")

        InclusionConnectState.objects.cleanup()

        state.refresh_from_db()
        self.assertIsNotNone(state)

        # Set expired creation time for the state
        state.created_at = timezone.now() - INCLUSION_CONNECT_STATE_EXPIRATION * 2
        state.save()

        InclusionConnectState.objects.cleanup()

        with self.assertRaises(InclusionConnectState.DoesNotExist):
            state.refresh_from_db()

    def test_create_user_from_user_info(self):
        """
        Nominal scenario: there is no user with the InclusionConnect ID or InclusionConnect email
        that is sent, so we create one.
        Similar to france_connect.tests.FranceConnectTest.test_create_user_from_user_data
        but with more tests.
        """
        user_info = INCLUSION_CONNECT_USERINFO
        ic_user_data = InclusionConnectUserData(**userinfo_to_user_model_dict(user_info))
        self.assertFalse(User.objects.filter(username=ic_user_data.username).exists())
        self.assertFalse(User.objects.filter(email=ic_user_data.email).exists())

        user, created = create_or_update_user(ic_user_data)
        self.assertTrue(created)
        self.assertEqual(user.email, user_info["email"])
        self.assertEqual(user.last_name, user_info["family_name"])
        self.assertEqual(user.first_name, user_info["given_name"])
        self.assertEqual(user.username, user_info["sub"])

        # TODO: this should be tested separately in User.test_models
        # TODO: update FC test to use PROVIDER_FRANCE_CONNECT instead.
        for field in dataclasses.fields(ic_user_data):
            self.assertEqual(user.external_data_source_history[field.name]["source"], PROVIDER_INCLUSION_CONNECT)
            self.assertEqual(user.external_data_source_history[field.name]["value"], getattr(user, field.name))
            self.assertEqual(user.external_data_source_history[field.name]["created_at"].date(), datetime.date.today())

    def test_create_user_from_user_info_with_already_existing_ic_id(self):
        """
        If there already is an existing user with this FranceConnectId, we do not create it again,
        we use it and we update it.
        Similar to france_connect.tests.FranceConnectTest.test_create_user_*
        """
        user_info = INCLUSION_CONNECT_USERINFO
        ic_user_data = InclusionConnectUserData(**userinfo_to_user_model_dict(user_info))
        UserFactory(username=ic_user_data.username, last_name="will_be_forgotten")
        user, created = create_or_update_user(ic_user_data)
        self.assertFalse(created)
        self.assertEqual(user.last_name, user_info["family_name"])
        self.assertEqual(user.first_name, user_info["given_name"])
        self.assertEqual(user.external_data_source_history["last_name"]["source"], PROVIDER_INCLUSION_CONNECT)

    def test_create_user_from_user_info_with_already_existing_ic_email(self):
        """
        If there already is an existing user with email InclusionConnect sent us, we do not create it again,
        we use it but we do not update it.
        Similar to france_connect.tests.FranceConnectTest.test_create_user_*
        TODO: (celine-m-s) Check this behaviour.
        """
        user_info = INCLUSION_CONNECT_USERINFO
        ic_user_data = InclusionConnectUserData(**userinfo_to_user_model_dict(user_info))
        UserFactory(email=ic_user_data.email)
        user, created = create_or_update_user(ic_user_data)
        self.assertFalse(created)
        self.assertNotEqual(user.last_name, user_info["family_name"])
        self.assertNotEqual(user.first_name, user_info["given_name"])
        # We did not fill this data using external data, so it is not set.
        self.assertIsNone(user.external_data_source_history)

    def test_update_user_from_user_info(self):
        user_info = INCLUSION_CONNECT_USERINFO
        user = UserFactory(**userinfo_to_user_model_dict(user_info))
        ic_user_data = InclusionConnectUserData(**userinfo_to_user_model_dict(user_info))

        # TODO: this should be tested separately.
        for field in dataclasses.fields(ic_user_data):
            value = getattr(ic_user_data, field.name)
            user.update_external_data_source_history_field(
                provider_name=PROVIDER_INCLUSION_CONNECT, field=field.name, value=value
            )
            user.save()

        new_user_data = InclusionConnectUserData(
            first_name="Jean", last_name="Gabin", username=ic_user_data.username, email="jean@lestontons.fr"
        )
        user, created = create_or_update_user(new_user_data)
        self.assertFalse(created)

        for field in dataclasses.fields(new_user_data):
            value = getattr(new_user_data, field.name)
            self.assertEqual(getattr(user, field.name), value)

        # TODO: this should be tested separately.
        # TODO: (celine-m-s) I'm not very comfortable with this behaviour as we don't really
        # keep a history of changes but only the last one.
        # Field name don't reflect actual behaviour.
        # Also, keeping a trace of old data is interesting in a debug purpose.
        for field in dataclasses.fields(new_user_data):
            self.assertEqual(user.external_data_source_history[field.name]["source"], PROVIDER_INCLUSION_CONNECT)
            self.assertEqual(user.external_data_source_history[field.name]["value"], getattr(user, field.name))
            # Because external_data_source_history is a JSONField,
            # dates are actually stored as strings in the database.
            created_at = user.external_data_source_history[field.name]["created_at"]
            if isinstance(created_at, str):
                created_at = datetime.datetime.fromisoformat(created_at[:19])  # Remove milliseconds
            self.assertEqual(created_at.date(), datetime.date.today())


class InclusionConnectViewTest(TestCase):
    def test_state_verification(self):
        csrf_signed = state_new()
        self.assertTrue(state_is_valid(csrf_signed))

    def test_callback_no_code(self):
        url = reverse("inclusion_connect:callback")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_callback_no_state(self):
        url = reverse("inclusion_connect:callback")
        response = self.client.get(url, data={"code": "123"})
        self.assertEqual(response.status_code, 302)

    def test_callback_invalid_state(self):
        url = reverse("inclusion_connect:callback")
        response = self.client.get(url, data={"code": "123", "state": "000"})
        self.assertEqual(response.status_code, 302)

    def test_authorize_endpoint(self):
        url = reverse("inclusion_connect:authorize")
        response = self.client.get(url, follow=False)
        # Don't use assertRedirects to avoid fetching the last URL.
        self.assertTrue(response.url.startswith(INCLUSION_CONNECT_ENDPOINT_AUTHORIZE))

    def test_authorize_endpoint_with_params(self):
        email = parse.quote("porthos@mousquetairestoujours.com")
        url = reverse("inclusion_connect:authorize") + f"?login_hint={email}"
        response = self.client.get(url, follow=False)
        self.assertIn(email, response.url)

    ####################################
    ######### Callback tests ###########
    ####################################

    @respx.mock
    def test_callback_user_created(self):
        ### User does not exist.
        _oauth_dance(self)
        self.assertEqual(User.objects.count(), 1)
        user = User.objects.get(email=INCLUSION_CONNECT_USERINFO["email"])
        self.assertEqual(user.first_name, INCLUSION_CONNECT_USERINFO["given_name"])
        self.assertEqual(user.last_name, INCLUSION_CONNECT_USERINFO["family_name"])
        self.assertEqual(user.username, INCLUSION_CONNECT_USERINFO["sub"])
        self.assertTrue(user.has_sso_provider)
        self.assertEqual(user.identity_provider, users_enums.IdentityProvider.INCLUSION_CONNECT)

    @respx.mock
    def test_callback_user_no_change(self):
        ### User already exists on Itou with exactly the same data
        # as in Inclusion Connect. No change should have been made.
        user_info = {
            "first_name": INCLUSION_CONNECT_USERINFO["given_name"],
            "last_name": INCLUSION_CONNECT_USERINFO["family_name"],
            "username": INCLUSION_CONNECT_USERINFO["sub"],
            "email": INCLUSION_CONNECT_USERINFO["email"],
        }
        UserFactory(**user_info)
        _oauth_dance(self)
        self.assertEqual(User.objects.count(), 1)
        user = User.objects.get(email=user_info["email"])
        self.assertEqual(user.first_name, user_info["first_name"])
        self.assertEqual(user.last_name, user_info["last_name"])
        self.assertEqual(user.username, user_info["username"])
        self.assertTrue(user.has_sso_provider)
        self.assertEqual(user.identity_provider, users_enums.IdentityProvider.INCLUSION_CONNECT)

    @respx.mock
    def test_callback_user_updated(self):
        # User already exists on Itou but some attributes differs.
        # An update should be made.
        UserFactory(
            first_name="Bernard",
            last_name="Blier",
            username=INCLUSION_CONNECT_USERINFO["sub"],
            email=INCLUSION_CONNECT_USERINFO["email"],
        )
        _oauth_dance(self)
        self.assertEqual(User.objects.count(), 1)
        user = User.objects.get(email=INCLUSION_CONNECT_USERINFO["email"])
        self.assertEqual(user.first_name, INCLUSION_CONNECT_USERINFO["given_name"])
        self.assertEqual(user.last_name, INCLUSION_CONNECT_USERINFO["family_name"])
        self.assertEqual(user.username, INCLUSION_CONNECT_USERINFO["sub"])
        self.assertTrue(user.has_sso_provider)
        self.assertEqual(user.identity_provider, users_enums.IdentityProvider.INCLUSION_CONNECT)


class InclusionConnectPrescribersViewsTest(TestCase):
    """
    Test prescribers' signup and login paths.
    """

    @respx.mock
    def test_prescriber_signup__no_organization(self):
        """
        A user creates a prescriber account on Itou with Inclusion Connect.
        This is a simple prescriber account ("orienteur"): no organization.
        """
        # Go through each step to ensure session data is recorded properly.
        # Step 1: choose organization kind or go to the "no organization" page.
        self.client.get(reverse("signup:prescriber_check_already_exists"))

        # Step 2: register as a simple prescriber (orienteur).
        response = self.client.get(reverse("signup:prescriber_user"))
        self.assertContains(response, "inclusion_connect_button.svg")

        # Connect with Inclusion Connect.
        # Skip the welcoming tour to test dashboard content.
        url = reverse("dashboard:index")
        with mock.patch("itou.users.adapter.UserAdapter.get_login_redirect_url", return_value=url):
            response = _oauth_dance(self, assert_redirects=False)
            # Follow the redirection.
            response = self.client.get(response.url)
        # Response should contain links available only to prescribers.
        self.assertContains(response, reverse("apply:list_for_prescriber"))

        user = User.objects.get(email=INCLUSION_CONNECT_USERINFO["email"])
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_job_seeker)
        self.assertFalse(user.is_siae_staff)
        self.assertFalse(user.is_labor_inspector)
        self.assertEqual(user.prescribermembership_set.count(), 0)
        self.assertEqual(user.siae_set.count(), 0)

    @respx.mock
    def test_prescriber_signup__pe_organization(self):
        """
        A user creates a prescriber account on Itou with Inclusion Connect.
        He wants to join a Pôle emploi organization (as first admin).
        """
        pe_org = PrescriberPoleEmploiFactory()
        email = f"maxime{settings.POLE_EMPLOI_EMAIL_SUFFIX}"

        # Go through each step to ensure session data is recorded properly.
        # Step 1: choose organization kind or go to the "no organization" page.
        self.client.get(reverse("signup:prescriber_check_already_exists"))

        # Step 2: find PE organization by SAFIR code.
        safir_step_url = reverse("signup:prescriber_pole_emploi_safir_code")
        response = self.client.get(safir_step_url)
        post_data = {"safir_code": pe_org.code_safir_pole_emploi}
        response = self.client.post(safir_step_url, data=post_data, follow=True)

        # Step 3: check email
        check_email_url = reverse("signup:prescriber_check_pe_email")
        post_data = {"email": f"athos{settings.POLE_EMPLOI_EMAIL_SUFFIX}"}
        response = self.client.post(check_email_url, data=post_data, follow=True)
        self.assertContains(response, "inclusion_connect_button.svg")

        # Connect with Inclusion Connect.
        # Skip the welcoming tour to test dashboard content.
        url = reverse("dashboard:index")
        with mock.patch("itou.users.adapter.UserAdapter.get_login_redirect_url", return_value=url):
            response = _oauth_dance(self, email=email, assert_redirects=False)
            # Follow the redirection.
            response = self.client.get(response.url)

        # Response should contain links available only to prescribers.
        self.assertContains(response, reverse("apply:list_for_prescriber"))

        # Organization
        self.assertEqual(self.client.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY), pe_org.pk)
        self.assertContains(response, f"Code SAFIR {pe_org.code_safir_pole_emploi}")

        user = User.objects.get(email=email)
        self.assertEqual(user.prescribermembership_set.count(), 1)
        self.assertEqual(user.prescribermembership_set.first().organization_id, pe_org.pk)
        self.assertEqual(user.siae_set.count(), 0)

    @respx.mock
    def test_prescriber_signup__unauthorized_organization(self):
        """
        A user creates a prescriber account on Itou with Inclusion Connect.
        He wants to create an unauthorized organization and join it (as first admin).
        """
        org = PrescriberOrganizationFactory.build(kind=PrescriberOrganization.Kind.OTHER)

        # Go through each step to ensure session data is recorded properly.
        # Step 1: find organization to join or go to the "no organization" page.
        find_org_url = reverse("signup:prescriber_check_already_exists")
        self.client.get(find_org_url)

        session_signup_data = self.client.session.get(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)

        # Jump over the last step to avoid double-testing each one:
        # as they are already tested on prescriber's signup views.
        # Prescriber's signup process heavily relies on session data.
        # Override only what's needed for our test.
        # PrescriberOrganizationFactoy does not contain any address field
        # so we can't use it.
        prescriber_org_data = {
            "siret": org.siret,
            "is_head_office": True,
            "name": org.name,
            "address_line_1": "17 RUE JEAN DE LA FONTAINE",
            "address_line_2": "",
            "post_code": "13150",
            "city": "TARASCON",
            "department": "13",
            "longitude": 4.660572,
            "latitude": 43.805661,
            "geocoding_score": 0.8178357293868921,
        }
        session_signup_data = session_signup_data | {
            "authorization_status": "NOT_SET",
            "kind": org.kind,
            "prescriber_org_data": prescriber_org_data,
        }
        client_session = self.client.session
        client_session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = session_signup_data
        client_session.save()

        response = self.client.get(reverse("signup:prescriber_user"))
        self.assertContains(response, "inclusion_connect_button.svg")

        # Connect with Inclusion Connect.
        # Skip the welcoming tour to test dashboard content.
        url = reverse("dashboard:index")
        with mock.patch("itou.users.adapter.UserAdapter.get_login_redirect_url", return_value=url):
            response = _oauth_dance(self, assert_redirects=False)
            # Follow the redirection.
            response = self.client.get(response.url)

        # Response should contain links available only to prescribers.
        self.assertContains(response, reverse("apply:list_for_prescriber"))

        org = PrescriberOrganization.objects.get(siret=org.siret)

        # Dashboard
        self.assertEqual(self.client.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY), org.pk)
        self.assertContains(response, org.display_name)

        # Created organization attributes
        self.assertEqual(org.authorization_status, PrescriberOrganization.AuthorizationStatus.NOT_SET)
        # self.assertTrue(org.is_head_office)
        self.assertFalse(org.is_authorized)

        # Interestingly enough, this attribute is ignored when
        # creating the organization.
        prescriber_org_data.pop("is_head_office")
        for key, value in prescriber_org_data.items():
            with self.subTest(key=key, value=value):
                self.assertEqual(getattr(org, key), value)

        # Membership
        user = User.objects.get(email=INCLUSION_CONNECT_USERINFO["email"])
        self.assertEqual(user.prescribermembership_set.count(), 1)
        self.assertEqual(user.prescribermembership_set.first().organization_id, org.pk)
        self.assertEqual(user.siae_set.count(), 0)


class InclusionConnectPrescribersViewsExceptionsTest(TestCase):
    """
    Prescribers' signup and login exceptions: user already exists, ...
    """

    @respx.mock
    def test_prescriber_already_exists__simple_signup(self):
        """
        He does not want to join an organization, only create an account.
        He likely forgot he had an account.
        """
        #### User is a prescriber. Update it and connect. ####
        PrescriberFactory(email=INCLUSION_CONNECT_USERINFO["email"])
        self.client.get(reverse("signup:prescriber_check_already_exists"))

        # Step 2: register as a simple prescriber (orienteur).
        response = self.client.get(reverse("signup:prescriber_user"))
        self.assertContains(response, "inclusion_connect_button.svg")

        # Connect with Inclusion Connect.
        # Skip the welcoming tour to test dashboard content.
        url = reverse("dashboard:index")
        with mock.patch("itou.users.adapter.UserAdapter.get_login_redirect_url", return_value=url):
            response = _oauth_dance(self, assert_redirects=False)
            # Follow the redirection.
            response = self.client.get(response.url)

        # Response should contain links available only to prescribers.
        self.assertContains(response, reverse("apply:list_for_prescriber"))

        User.objects.get(email=INCLUSION_CONNECT_USERINFO["email"])
        # self.assertTrue(user.has_sso_provider)

    @respx.mock
    def test_prescriber_already_exists__create_organization(self):
        """
        User is already a prescriber.
        We should update his account and make him join this new organization.
        But as long as the code uses PrescriberSignupForms, this is complicated.
        At the same time, this is quite unlikely to happen (confirmed by Zohra).
        Propose to ask the support team.
        """
        org = PrescriberOrganizationFactory.build(kind=PrescriberOrganization.Kind.OTHER)
        user = PrescriberFactory(email=INCLUSION_CONNECT_USERINFO["email"])

        self.client.get(reverse("signup:prescriber_check_already_exists"))

        session_signup_data = self.client.session.get(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
        # Jump over the last step to avoid double-testing each one:
        # as they are already tested on prescriber's signup views.
        # Prescriber's signup process heavily relies on session data.
        # Override only what's needed for our test.
        # PrescriberOrganizationFactoy does not contain any address field
        # so we can't use it.
        prescriber_org_data = {
            "siret": org.siret,
            "is_head_office": True,
            "name": org.name,
            "address_line_1": "17 RUE JEAN DE LA FONTAINE",
            "address_line_2": "",
            "post_code": "13150",
            "city": "TARASCON",
            "department": "13",
            "longitude": 4.660572,
            "latitude": 43.805661,
            "geocoding_score": 0.8178357293868921,
        }
        session_signup_data = session_signup_data | {
            "authorization_status": "NOT_SET",
            "kind": org.kind,
            "prescriber_org_data": prescriber_org_data,
        }

        client_session = self.client.session
        client_session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = session_signup_data
        client_session.save()
        signup_url = reverse("signup:prescriber_user")

        response = self.client.get(signup_url)
        self.assertContains(response, "inclusion_connect_button.svg")

        # Connect with Inclusion Connect.
        response = _oauth_dance(self, assert_redirects=False)
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)

        # Show an error and don't create an organization.
        self.assertEqual(response.wsgi_request.path, signup_url)
        self.assertNotContains(response, reverse("apply:list_for_prescriber"))
        self.assertContains(response, "inclusion_connect_button.svg")
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        error_message = "Un compte existe déjà avec cette adresse e-mail"
        self.assertIn(error_message, str(messages[0]))
        self.assertIn(settings.ITOU_ASSISTANCE_URL, str(messages[0]))
        self.assertNotIn("*", str(messages[0]))

        user = User.objects.get(email=INCLUSION_CONNECT_USERINFO["email"])
        self.assertNotEqual(user.first_name, INCLUSION_CONNECT_USERINFO["given_name"])
        organization_exists = PrescriberOrganization.objects.filter(siret=org.siret).exists()
        self.assertFalse(organization_exists)
        self.assertFalse(user.prescriberorganization_set.exists())

    @respx.mock
    def test_employer_already_exists(self):
        """
        User is already a member of an SIAE.
        Raise an exception.
        """
        org = PrescriberOrganizationFactory.build(kind=PrescriberOrganization.Kind.OTHER)
        user = SiaeStaffFactory(email=INCLUSION_CONNECT_USERINFO["email"])
        self.client.get(reverse("signup:prescriber_check_already_exists"))

        session_signup_data = self.client.session.get(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
        # Jump over the last step to avoid double-testing each one:
        # as they are already tested on prescriber's signup views.
        # Prescriber's signup process heavily relies on session data.
        # Override only what's needed for our test.
        # PrescriberOrganizationFactoy does not contain any address field
        # so we can't use it.
        prescriber_org_data = {
            "siret": org.siret,
            "is_head_office": True,
            "name": org.name,
            "address_line_1": "17 RUE JEAN DE LA FONTAINE",
            "address_line_2": "",
            "post_code": "13150",
            "city": "TARASCON",
            "department": "13",
            "longitude": 4.660572,
            "latitude": 43.805661,
            "geocoding_score": 0.8178357293868921,
        }
        session_signup_data = session_signup_data | {
            "authorization_status": "NOT_SET",
            "kind": org.kind,
            "prescriber_org_data": prescriber_org_data,
        }

        client_session = self.client.session
        client_session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = session_signup_data
        client_session.save()
        signup_url = reverse("signup:prescriber_user")

        response = self.client.get(signup_url)
        self.assertContains(response, "inclusion_connect_button.svg")

        # Connect with Inclusion Connect.
        response = _oauth_dance(self, assert_redirects=False)
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)

        # Show an error and don't create an organization.
        self.assertEqual(response.wsgi_request.path, signup_url)
        self.assertNotContains(response, reverse("apply:list_for_prescriber"))
        self.assertContains(response, "inclusion_connect_button.svg")
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        error_message = "Un compte existe déjà avec cette adresse e-mail"
        self.assertIn(error_message, str(messages[0]))

        user = User.objects.get(email=INCLUSION_CONNECT_USERINFO["email"])
        self.assertNotEqual(user.first_name, INCLUSION_CONNECT_USERINFO["given_name"])
        organization_exists = PrescriberOrganization.objects.filter(siret=org.siret).exists()
        self.assertFalse(organization_exists)
        self.assertFalse(user.prescriberorganization_set.exists())

    @respx.mock
    def test_prescriber_signup__pe_organization_wrong_email(self):
        """
        A user creates a prescriber account on Itou with Inclusion Connect.
        He wants to join a Pôle emploi organization
        but his e-mail suffix is wrong. An error should be raised.
        """
        pe_org = PrescriberPoleEmploiFactory()
        email = f"maxime{settings.POLE_EMPLOI_EMAIL_SUFFIX}"

        # Go through each step to ensure session data is recorded properly.
        # Step 1: choose organization kind or go to the "no organization" page.
        self.client.get(reverse("signup:prescriber_check_already_exists"))

        # Step 2: find PE organization by SAFIR code.
        safir_step_url = reverse("signup:prescriber_pole_emploi_safir_code")
        response = self.client.get(safir_step_url)
        post_data = {"safir_code": pe_org.code_safir_pole_emploi}
        response = self.client.post(safir_step_url, data=post_data, follow=True)

        # Step 3: check email
        check_email_url = reverse("signup:prescriber_check_pe_email")
        post_data = {"email": f"athos{settings.POLE_EMPLOI_EMAIL_SUFFIX}"}
        response = self.client.post(check_email_url, data=post_data, follow=True)
        self.assertContains(response, "inclusion_connect_button.svg")

        # Connect with Inclusion Connect but, this time, don't use a PE email.
        url = reverse("dashboard:index")
        with mock.patch("itou.users.adapter.UserAdapter.get_login_redirect_url", return_value=url):
            response = _oauth_dance(self, assert_redirects=False)
            # Follow the redirection.
            response = self.client.get(response.url, follow=True)

        self.assertNotContains(response, reverse("apply:list_for_prescriber"))
        self.assertContains(response, "inclusion_connect_button.svg")
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn(
            "L’adresse e-mail que vous avez utilisée n’est pas une adresse e-mail en pole-emploi.fr.",
            str(messages[0]),
        )

        # Organization
        self.assertFalse(self.client.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY))
        self.assertFalse(User.objects.filter(email=email).exists())


class InclusionConnectLogoutTest(TestCase):
    @respx.mock
    def test_django_account_logout_from_ic(self):
        """
        When ac IC wants to log out from his local account,
        he should be logged out too from IC.
        """
        response = _oauth_dance(self)
        self.assertTrue(auth.get_user(self.client).is_authenticated)
        # Follow the redirection.
        response = self.client.get(response.url)
        logout_url = reverse("account_logout")
        self.assertContains(response, logout_url)

        response = self.client.post(logout_url)
        expected_redirection = reverse("inclusion_connect:logout")
        # For simplicity, exclude GET params. They are tested elsewhere anyway..
        self.assertTrue(response.url.startswith(expected_redirection))

        response = self.client.get(response.url)
        # The following redirection is tested in self.test_logout_with_redirection
        self.assertEqual(response.status_code, 302)
        self.assertFalse(auth.get_user(self.client).is_authenticated)

    def test_django_account_logout(self):
        """
        When a local user wants to log out from his local account,
        he should be logged out without inclusion connect.
        """
        user = PrescriberFactory()
        self.client.login(email=user.email, password=DEFAULT_PASSWORD)
        response = self.client.post(reverse("account_logout"))
        expected_redirection = reverse("home:hp")
        self.assertRedirects(response, expected_redirection)
        self.assertFalse(auth.get_user(self.client).is_authenticated)

    @respx.mock
    def test_simple_logout(self):
        _oauth_dance(self)
        response = _logout_from_IC(self)
        expected_redirection = reverse("home:hp")
        self.assertRedirects(response, expected_redirection)

    @respx.mock
    def test_logout_with_redirection(self):
        _oauth_dance(self)
        expected_redirection = reverse("dashboard:index")
        response = _logout_from_IC(self, redirect_url=expected_redirection)
        self.assertRedirects(response, expected_redirection)

    def test_logout_exception_no_id_token(self):
        url = reverse("inclusion_connect:logout")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["message"], "Le paramètre « id_token » est manquant.")


class InclusionConnectLoginTest(TestCase):
    @respx.mock
    def test_normal_signin(self):
        """
        A user has created an account with Inclusion Connect.
        He logs out.
        He can log in again later.
        """
        # Create an account with IC.
        _oauth_dance(self)

        # Then log out.
        response = self.client.post(reverse("account_logout"))

        # Then log in again.
        login_url = reverse("login:prescriber")
        response = self.client.get(login_url)
        self.assertContains(response, "inclusion_connect_button.svg")

        response = _oauth_dance(self, assert_redirects=False)
        expected_redirection = reverse("dashboard:index")
        self.assertRedirects(response, expected_redirection)

        # Make sure it was a login instead of a new signup.
        users_count = User.objects.filter(email=INCLUSION_CONNECT_USERINFO["email"]).count()
        self.assertEqual(users_count, 1)

    @respx.mock
    def test_old_django_account(self):
        """
        A user has a Django account.
        He clicks on IC button and creates his account.
        His old Django account should now be considered as an IC one.
        """
        user_info = INCLUSION_CONNECT_USERINFO
        user = PrescriberFactory(**userinfo_to_user_model_dict(user_info), has_completed_welcoming_tour=True)

        # Existing user connects with IC which results in:
        # - IC side: account creation
        # - Django side: account update.
        # This logic is already tested here: InclusionConnectModelTest
        response = _oauth_dance(self, assert_redirects=False)
        # This existing user should not see the welcoming tour.
        expected_redirection = reverse("dashboard:index")
        self.assertRedirects(response, expected_redirection)
        self.assertTrue(auth.get_user(self.client).is_authenticated)
        # Make sure it was a login instead of a new signup.
        users_count = User.objects.filter(email=INCLUSION_CONNECT_USERINFO["email"]).count()
        self.assertEqual(users_count, 1)

        response = self.client.post(reverse("account_logout"))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(auth.get_user(self.client).is_authenticated)

        # Try to login with Django.
        # This is already tested in itou.www.login.tests but only at form level.
        post_data = {"login": user.email, "password": DEFAULT_PASSWORD}
        response = self.client.post(reverse("login:prescriber"), data=post_data)
        self.assertEqual(response.status_code, 200)
        error_message = "Votre compte est relié à Inclusion Connect."
        self.assertContains(response, error_message)

        # Then login with Inclusion Connect.
        _oauth_dance(self, assert_redirects=False)
        self.assertTrue(auth.get_user(self.client).is_authenticated)


class InclusionConnectUserPermissions(TestCase):
    """
    A user how created his account with IC should not be able
    to perform the same actions as someone who did it with Django auth.
    """

    def test_cannot_update_password(self):
        # Don't show the form.
        # Done in another PR.

        # Don't allow update.
        pass
