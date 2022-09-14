import dataclasses
import json
from operator import itemgetter
from unittest import mock
from urllib.parse import quote, urlencode

import httpx
import respx
from django.contrib import auth
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from itou.openid_connect.inclusion_connect.views import InclusionConnectSession
from itou.users import enums as users_enums
from itou.users.enums import KIND_PRESCRIBER, KIND_SIAE_STAFF
from itou.users.factories import DEFAULT_PASSWORD, PrescriberFactory, UserFactory
from itou.users.models import User

from ..constants import OIDC_STATE_EXPIRATION
from ..models import TooManyKindsException
from . import constants
from .models import InclusionConnectPrescriberData, InclusionConnectSiaeStaffData, InclusionConnectState
from .testing import InclusionConnectBaseTestCase


OIDC_USERINFO = {
    "given_name": "Michel",
    "family_name": "AUDIARD",
    "email": "michel@lestontons.fr",
    "sub": "af6b26f9-85cd-484e-beb9-bea5be13e30f",
}


# Make sure this decorator is before test definition, not here.
# @respx.mock
def mock_oauth_dance(
    test_class,
    user_kind,
    previous_url=None,
    next_url=None,
    assert_redirects=True,
    expected_route="welcoming_tour:index",
    login_hint=None,
    user_info_email=None,
    channel=None,
):
    assert user_kind, "Letting this filed empty is not allowed"
    respx.get(constants.INCLUSION_CONNECT_ENDPOINT_AUTHORIZE).respond(302)
    # Authorize params depend on user kind.
    authorize_params = {
        "user_kind": user_kind,
        "previous_url": previous_url,
        "next_url": next_url,
        "login_hint": login_hint,
        "channel": channel,
    }
    authorize_params = {k: v for k, v in authorize_params.items() if v}

    # Calling this view is mandatory to start a new session.
    authorize_url = f"{reverse('inclusion_connect:authorize')}?{urlencode(authorize_params)}"
    test_class.client.get(authorize_url)

    # User is logged out from IC when an error happens during the oauth dance.
    respx.get(constants.INCLUSION_CONNECT_ENDPOINT_LOGOUT).respond(200)

    token_json = {"access_token": "7890123", "token_type": "Bearer", "expires_in": 60, "id_token": "123456"}
    respx.post(constants.INCLUSION_CONNECT_ENDPOINT_TOKEN).mock(return_value=httpx.Response(200, json=token_json))

    user_info = OIDC_USERINFO.copy()
    if user_info_email:
        user_info["email"] = user_info_email
    respx.get(constants.INCLUSION_CONNECT_ENDPOINT_USERINFO).mock(return_value=httpx.Response(200, json=user_info))

    csrf_signed = InclusionConnectState.create_signed_csrf_token()
    url = reverse("inclusion_connect:callback")
    response = test_class.client.get(url, data={"code": "123", "state": csrf_signed})
    if assert_redirects:
        test_class.assertRedirects(response, reverse(expected_route))

    return response


class InclusionConnectModelTest(InclusionConnectBaseTestCase):
    def test_state_delete(self):
        state = InclusionConnectState.objects.create(csrf="foo")

        InclusionConnectState.objects.cleanup()

        state.refresh_from_db()
        self.assertIsNotNone(state)

        state.created_at = timezone.now() - OIDC_STATE_EXPIRATION * 2
        state.save()

        InclusionConnectState.objects.cleanup()

        with self.assertRaises(InclusionConnectState.DoesNotExist):
            state.refresh_from_db()

    def test_create_user_from_user_info(self):
        """
        Nominal scenario: there is no user with the InclusionConnect ID or InclusionConnect email
        that is sent, so we create one.
        Similar to france_connect.tests.FranceConnectTest.test_create_django_user
        but with more tests.
        """
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)
        self.assertFalse(User.objects.filter(username=ic_user_data.username).exists())
        self.assertFalse(User.objects.filter(email=ic_user_data.email).exists())

        now = timezone.now()
        # Because external_data_source_history is a JSONField
        # dates are actually stored as strings in the database
        now_str = json.loads(DjangoJSONEncoder().encode(now))
        with mock.patch("django.utils.timezone.now", return_value=now):
            user, created = ic_user_data.create_or_update_user()
        self.assertTrue(created)
        self.assertEqual(user.email, OIDC_USERINFO["email"])
        self.assertEqual(user.last_name, OIDC_USERINFO["family_name"])
        self.assertEqual(user.first_name, OIDC_USERINFO["given_name"])
        self.assertEqual(user.username, OIDC_USERINFO["sub"])

        user.refresh_from_db()
        expected = [
            {
                "field_name": field.name,
                "value": getattr(user, field.name),
                "source": "IC",
                "created_at": now_str,
            }
            for field in dataclasses.fields(ic_user_data)
        ]
        self.assertEqual(
            sorted(user.external_data_source_history, key=itemgetter("field_name")),
            sorted(expected, key=itemgetter("field_name")),
        )

    def test_create_user_from_user_info_with_already_existing_id(self):
        """
        If there already is an existing user with this InclusionConnect id, we do not create it again,
        we use it and we update it.
        """
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)
        UserFactory(
            username=ic_user_data.username,
            last_name="will_be_forgotten",
            identity_provider=users_enums.IdentityProvider.INCLUSION_CONNECT,
        )
        user, created = ic_user_data.create_or_update_user()
        self.assertFalse(created)
        self.assertEqual(user.last_name, OIDC_USERINFO["family_name"])
        self.assertEqual(user.first_name, OIDC_USERINFO["given_name"])
        self.assertEqual(user.external_data_source_history[0]["source"], "IC")

    def test_create_user_from_user_info_with_already_existing_id_but_from_other_sso(self):
        """
        If there already is an existing user with this InclusionConnect id, but it comes from another SSO.
        The email is also different, so it will crash while trying to create a new user.
        """
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)
        UserFactory(
            username=ic_user_data.username,
            last_name="will_be_forgotten",
            identity_provider=users_enums.IdentityProvider.DJANGO,
            email="random@email.com",
        )
        with self.assertRaises(ValidationError):
            ic_user_data.create_or_update_user()

    def test_get_existing_user_with_same_email_django(self):
        """
        If there already is an existing django user with email InclusionConnect sent us, we do not create it again,
        We user it and we update it with the data form the identity_provider.
        """
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)
        UserFactory(email=ic_user_data.email, identity_provider=users_enums.IdentityProvider.DJANGO)
        user, created = ic_user_data.create_or_update_user()
        self.assertFalse(created)
        self.assertEqual(user.last_name, OIDC_USERINFO["family_name"])
        self.assertEqual(user.first_name, OIDC_USERINFO["given_name"])
        self.assertEqual(user.username, OIDC_USERINFO["sub"])
        self.assertEqual(user.identity_provider, users_enums.IdentityProvider.INCLUSION_CONNECT)

    def test_get_existing_user_with_same_email_other_SSO(self):
        """
        If there already is an existing user with email InclusionConnect sent us, we do not create it again,
        we use it but we do not update it.
        """
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)
        UserFactory(email=ic_user_data.email, identity_provider=users_enums.IdentityProvider.FRANCE_CONNECT)
        user, created = ic_user_data.create_or_update_user()
        self.assertFalse(created)
        self.assertNotEqual(user.last_name, OIDC_USERINFO["family_name"])
        self.assertNotEqual(user.first_name, OIDC_USERINFO["given_name"])
        self.assertNotEqual(user.username, OIDC_USERINFO["sub"])
        self.assertNotEqual(user.identity_provider, users_enums.IdentityProvider.INCLUSION_CONNECT)

    def test_update_user_from_user_info(self):
        user = UserFactory(**dataclasses.asdict(InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)))
        ic_user = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)

        new_ic_user = InclusionConnectPrescriberData(
            first_name="Jean", last_name="Gabin", username=ic_user.username, email="jean@lestontons.fr"
        )
        now = timezone.now()
        # Because external_data_source_history is a JSONField
        # dates are actually stored as strings in the database
        now_str = json.loads(DjangoJSONEncoder().encode(now))
        with mock.patch("django.utils.timezone.now", return_value=now):
            user, created = new_ic_user.create_or_update_user()
        self.assertFalse(created)

        user.refresh_from_db()
        expected = [
            {
                "field_name": field.name,
                "value": getattr(user, field.name),
                "source": "IC",
                "created_at": now_str,
            }
            for field in dataclasses.fields(ic_user)
        ]
        self.assertEqual(
            sorted(user.external_data_source_history, key=itemgetter("field_name")),
            sorted(expected, key=itemgetter("field_name")),
        )

    def test_state_is_valid(self):
        csrf_signed = InclusionConnectState.create_signed_csrf_token()
        self.assertTrue(isinstance(csrf_signed, str))
        self.assertTrue(InclusionConnectState.is_valid(csrf_signed))

    def test_create_or_update_prescriber_raise_too_many_kind_exception(self):
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)

        for field in ["is_job_seeker", "is_siae_staff", "is_labor_inspector"]:
            user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, **{field: True})

            with self.assertRaises(TooManyKindsException):
                ic_user_data.create_or_update_user()

            user.delete()

    def test_create_or_update_siae_staff_raise_too_many_kind_exception(self):
        ic_user_data = InclusionConnectSiaeStaffData.from_user_info(OIDC_USERINFO)

        for field in ["is_job_seeker", "is_prescriber", "is_labor_inspector"]:
            user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, **{field: True})

            with self.assertRaises(TooManyKindsException):
                ic_user_data.create_or_update_user()

            user.delete()


class InclusionConnectViewTest(InclusionConnectBaseTestCase):
    def test_callback_invalid_state(self):
        url = reverse("inclusion_connect:callback")
        response = self.client.get(url, data={"code": "123", "state": "000"})
        self.assertEqual(response.status_code, 302)

    def test_callback_no_state(self):
        url = reverse("inclusion_connect:callback")
        response = self.client.get(url, data={"code": "123"})
        self.assertEqual(response.status_code, 302)

    def test_callback_no_code(self):
        url = reverse("inclusion_connect:callback")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_authorize_endpoint(self):
        url = reverse("inclusion_connect:authorize")
        with self.assertRaises(KeyError):
            response = self.client.get(url, follow=False)

        url = f"{reverse('inclusion_connect:authorize')}?user_kind={KIND_PRESCRIBER}"
        # Don't use assertRedirects to avoid fetching the last URL.
        response = self.client.get(url, follow=False)
        self.assertTrue(response.url.startswith(constants.INCLUSION_CONNECT_ENDPOINT_AUTHORIZE))
        self.assertIn(constants.INCLUSION_CONNECT_SESSION_KEY, self.client.session)

    def test_authorize_endpoint_with_params(self):
        email = "porthos@touspourun.com"
        params = {"login_hint": email, "user_kind": KIND_PRESCRIBER, "channel": "invitation"}
        url = f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}"
        response = self.client.get(url, follow=False)
        self.assertIn(quote(email), response.url)
        self.assertEqual(self.client.session[constants.INCLUSION_CONNECT_SESSION_KEY]["user_email"], email)

    ####################################
    ######### Callback tests ###########
    ####################################
    @respx.mock
    def test_callback_prescriber_created(self):
        ### User does not exist.
        mock_oauth_dance(self, KIND_PRESCRIBER)
        self.assertEqual(User.objects.count(), 1)
        user = User.objects.get(email=OIDC_USERINFO["email"])
        self.assertEqual(user.first_name, OIDC_USERINFO["given_name"])
        self.assertEqual(user.last_name, OIDC_USERINFO["family_name"])
        self.assertEqual(user.username, OIDC_USERINFO["sub"])
        self.assertTrue(user.has_sso_provider)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)
        self.assertEqual(user.identity_provider, users_enums.IdentityProvider.INCLUSION_CONNECT)

    @respx.mock
    def test_callback_siae_staff_created(self):
        ### User does not exist.
        # Don't check redirection as the user isn't an siae member yet, so it won't work.
        mock_oauth_dance(self, KIND_SIAE_STAFF, assert_redirects=False)
        self.assertEqual(User.objects.count(), 1)
        user = User.objects.get(email=OIDC_USERINFO["email"])
        self.assertEqual(user.first_name, OIDC_USERINFO["given_name"])
        self.assertEqual(user.last_name, OIDC_USERINFO["family_name"])
        self.assertEqual(user.username, OIDC_USERINFO["sub"])
        self.assertTrue(user.has_sso_provider)
        self.assertFalse(user.is_prescriber)
        self.assertTrue(user.is_siae_staff)
        self.assertEqual(user.identity_provider, users_enums.IdentityProvider.INCLUSION_CONNECT)

    @respx.mock
    def test_callback_existing_django_user(self):
        # User created with django already exists on Itou but some attributes differs.
        # Update all fields
        UserFactory(
            first_name="Bernard",
            last_name="Blier",
            username="bernard_blier",
            email=OIDC_USERINFO["email"],
            identity_provider=users_enums.IdentityProvider.DJANGO,
        )
        mock_oauth_dance(self, KIND_PRESCRIBER)
        self.assertEqual(User.objects.count(), 1)
        user = User.objects.get(email=OIDC_USERINFO["email"])
        self.assertEqual(user.first_name, OIDC_USERINFO["given_name"])
        self.assertEqual(user.last_name, OIDC_USERINFO["family_name"])
        self.assertEqual(user.username, OIDC_USERINFO["sub"])
        self.assertTrue(user.has_sso_provider)
        self.assertEqual(user.identity_provider, users_enums.IdentityProvider.INCLUSION_CONNECT)

    @respx.mock
    def test_callback_redirect_prescriber_on_too_many_kind_exception(self):
        ic_user_data = InclusionConnectPrescriberData.from_user_info(OIDC_USERINFO)

        for field in ["is_job_seeker", "is_siae_staff", "is_labor_inspector"]:
            user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, **{field: True})
            response = mock_oauth_dance(self, KIND_PRESCRIBER, assert_redirects=False)
            response = self.client.get(response.url, follow=True)
            self.assertContains(response, "existe déjà avec cette adresse e-mail")
            self.assertContains(response, "pour devenir prescripteur sur la plateforme")
            user.delete()

    @respx.mock
    def test_callback_redirect_siae_staff_on_too_many_kind_exception(self):
        ic_user_data = InclusionConnectSiaeStaffData.from_user_info(OIDC_USERINFO)

        for field in ["is_job_seeker", "is_prescriber", "is_labor_inspector"]:
            user = UserFactory(username=ic_user_data.username, email=ic_user_data.email, **{field: True})
            # Don't check redirection as the user isn't an siae member yet, so it won't work.
            response = mock_oauth_dance(self, KIND_SIAE_STAFF, assert_redirects=False)
            response = self.client.get(response.url, follow=True)
            self.assertContains(response, "existe déjà avec cette adresse e-mail")
            self.assertContains(response, "pour devenir employeur sur la plateforme")
            user.delete()


class InclusionConnectSessionTest(InclusionConnectBaseTestCase):
    def test_start_session(self):
        ic_session = InclusionConnectSession()
        self.assertEqual(ic_session.key, constants.INCLUSION_CONNECT_SESSION_KEY)

        expected_keys = ["token", "state", "previous_url", "next_url", "user_email", "user_kind", "request"]
        ic_session_dict = ic_session.asdict()
        for key in expected_keys:
            with self.subTest(key):
                self.assertIn(key, ic_session_dict.keys())
                self.assertEqual(ic_session_dict[key], None)

        request = RequestFactory().get("/")
        middleware = SessionMiddleware(lambda x: x)
        middleware.process_request(request)
        request.session.save()
        request = ic_session.bind_to_request(request=request)
        self.assertTrue(request.session.get(constants.INCLUSION_CONNECT_SESSION_KEY))


class InclusionConnectLoginTest(InclusionConnectBaseTestCase):
    @respx.mock
    def test_normal_signin(self):
        """
        A user has created an account with Inclusion Connect.
        He logs out.
        He can log in again later.
        """
        # Create an account with IC.
        mock_oauth_dance(self, KIND_PRESCRIBER)

        # Then log out.
        response = self.client.post(reverse("account_logout"))

        # Then log in again.
        login_url = reverse("login:prescriber")
        response = self.client.get(login_url)
        self.assertContains(response, "inclusion_connect_button.svg")
        self.assertContains(response, reverse("inclusion_connect:authorize"))

        response = mock_oauth_dance(self, KIND_PRESCRIBER, assert_redirects=False)
        expected_redirection = reverse("dashboard:index")
        self.assertRedirects(response, expected_redirection)

        # Make sure it was a login instead of a new signup.
        users_count = User.objects.filter(email=OIDC_USERINFO["email"]).count()
        self.assertEqual(users_count, 1)

    @respx.mock
    def test_old_django_account(self):
        """
        A user has a Django account.
        He clicks on IC button and creates his account.
        His old Django account should now be considered as an IC one.
        """
        user_info = OIDC_USERINFO
        user = PrescriberFactory(
            has_completed_welcoming_tour=True,
            **InclusionConnectPrescriberData.user_info_mapping_dict(user_info),
        )

        # Existing user connects with IC which results in:
        # - IC side: account creation
        # - Django side: account update.
        # This logic is already tested here: InclusionConnectModelTest
        response = mock_oauth_dance(self, KIND_PRESCRIBER, assert_redirects=False)
        # This existing user should not see the welcoming tour.
        expected_redirection = reverse("dashboard:index")
        self.assertRedirects(response, expected_redirection)
        self.assertTrue(auth.get_user(self.client).is_authenticated)
        # Make sure it was a login instead of a new signup.
        users_count = User.objects.filter(email=OIDC_USERINFO["email"]).count()
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
        self.assertFalse(auth.get_user(self.client).is_authenticated)

        # Then login with Inclusion Connect.
        mock_oauth_dance(self, KIND_PRESCRIBER, assert_redirects=False)
        self.assertTrue(auth.get_user(self.client).is_authenticated)


class InclusionConnectLogoutTest(InclusionConnectBaseTestCase):
    @respx.mock
    def test_simple_logout(self):
        mock_oauth_dance(self, KIND_PRESCRIBER)
        respx.get(constants.INCLUSION_CONNECT_ENDPOINT_LOGOUT).respond(200)
        logout_url = reverse("inclusion_connect:logout")
        response = self.client.get(logout_url)
        self.assertRedirects(response, reverse("home:hp"))

    @respx.mock
    def test_logout_with_redirection(self):
        mock_oauth_dance(self, KIND_PRESCRIBER)
        expected_redirection = reverse("dashboard:index")
        respx.get(constants.INCLUSION_CONNECT_ENDPOINT_LOGOUT).respond(200)

        params = {"redirect_url": expected_redirection}
        logout_url = f"{reverse('inclusion_connect:logout')}?{urlencode(params)}"
        response = self.client.get(logout_url)
        self.assertRedirects(response, expected_redirection)

    @respx.mock
    def test_django_account_logout_from_ic(self):
        """
        When ac IC user wants to log out from his local account,
        he should be logged out too from IC.
        """
        response = mock_oauth_dance(self, KIND_PRESCRIBER)
        self.assertTrue(auth.get_user(self.client).is_authenticated)
        # Follow the redirection.
        response = self.client.get(response.url)
        logout_url = reverse("account_logout")
        self.assertContains(response, logout_url)
        self.assertTrue(self.client.session.get(constants.INCLUSION_CONNECT_SESSION_KEY))

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
        user = UserFactory()
        self.client.force_login(user)
        response = self.client.post(reverse("account_logout"))
        expected_redirection = reverse("home:hp")
        self.assertRedirects(response, expected_redirection)
        self.assertFalse(auth.get_user(self.client).is_authenticated)

    @respx.mock
    def test_logout_with_incomplete_state(self):
        # This happens while testing. It should never happen for real users, but it's still painful for us.

        mock_oauth_dance(self, KIND_PRESCRIBER)
        respx.get(constants.INCLUSION_CONNECT_ENDPOINT_LOGOUT).respond(200)

        session = self.client.session
        session[constants.INCLUSION_CONNECT_SESSION_KEY]["token"] = None
        session[constants.INCLUSION_CONNECT_SESSION_KEY]["state"] = None
        session.save()

        response = self.client.post(reverse("account_logout"))
        expected_redirection = reverse("home:hp")
        self.assertRedirects(response, expected_redirection)
