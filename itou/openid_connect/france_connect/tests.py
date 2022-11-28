import datetime

import httpx
import respx
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from itou.openid_connect.constants import OIDC_STATE_CLEANUP
from itou.users.enums import IdentityProvider
from itou.users.factories import UserFactory
from itou.users.models import User
from itou.utils.testing import reload_module

from ..models import TooManyKindsException
from . import constants
from .models import FranceConnectState, FranceConnectUserData


FC_USERINFO = {
    "given_name": "Angela Claire Louise",
    "family_name": "DUBOIS",
    "birthdate": "1962-08-24",
    "gender": "female",
    "birthplace": "75107",
    "birthcountry": "99100",
    "email": "wossewodda-3728@yopmail.com",
    "address": {
        "country": "France",
        "formatted": "France Paris 75107 20 avenue de Ségur",
        "locality": "Paris",
        "postal_code": "75107",
        "street_address": "20 avenue de Ségur",
    },
    "phone_number": "123456789",
    "sub": "b6048e95bb134ec5b1d1e1fa69f287172e91722b9354d637a1bcf2ebb0fd2ef5v1",
}


# Make sure this decorator is before test definition, not here.
# @respx.mock
def mock_oauth_dance(test_class, expected_route="dashboard:index"):
    # No session is created with France Connect in contrary to Inclusion Connect
    # so there's no use to go through france_connect:authorize

    token_json = {"access_token": "7890123", "token_type": "Bearer", "expires_in": 60, "id_token": "123456"}
    respx.post(constants.FRANCE_CONNECT_ENDPOINT_TOKEN).mock(return_value=httpx.Response(200, json=token_json))

    user_info = FC_USERINFO.copy()
    respx.get(constants.FRANCE_CONNECT_ENDPOINT_USERINFO).mock(return_value=httpx.Response(200, json=user_info))

    csrf_signed = FranceConnectState.create_signed_csrf_token()
    url = reverse("france_connect:callback")
    response = test_class.client.get(url, data={"code": "123", "state": csrf_signed})
    test_class.assertRedirects(response, reverse(expected_route))
    return response


@override_settings(
    FRANCE_CONNECT_BASE_URL="https://france.connect.fake",
    FRANCE_CONNECT_CLIENT_ID="FC_CLIENT_ID_123",
    FRANCE_CONNECT_CLIENT_SECRET="FC_CLIENT_SECRET_123",
)
@reload_module(constants)
class FranceConnectTest(TestCase):
    def test_state_delete(self):
        state = FranceConnectState.objects.create(csrf="foo")

        FranceConnectState.objects.cleanup()

        state.refresh_from_db()
        self.assertIsNotNone(state)

        # Set expired creation time for the state
        state.expired_at = timezone.now() - OIDC_STATE_CLEANUP * 2
        state.save()

        FranceConnectState.objects.cleanup()

        with self.assertRaises(FranceConnectState.DoesNotExist):
            state.refresh_from_db()

    def test_state_verification(self):
        csrf_signed = FranceConnectState.create_signed_csrf_token()
        self.assertTrue(FranceConnectState.get_from_csrf(csrf_signed).is_valid())

    def test_state_is_valid(self):
        with freeze_time("2022-09-13 12:00:01"):
            csrf_signed = FranceConnectState.create_signed_csrf_token()
            self.assertTrue(isinstance(csrf_signed, str))
            self.assertTrue(FranceConnectState.get_from_csrf(csrf_signed).is_valid())

            csrf_signed = FranceConnectState.create_signed_csrf_token()
        with freeze_time("2022-09-13 13:00:01"):
            self.assertFalse(FranceConnectState.get_from_csrf(csrf_signed).is_valid())

    def test_authorize(self):
        url = reverse("france_connect:authorize")
        response = self.client.get(url, follow=False)
        # Don't use assertRedirects to avoid fetch
        self.assertTrue(response.url.startswith(constants.FRANCE_CONNECT_ENDPOINT_AUTHORIZE))

    def test_create_django_user(self):
        """
        Nominal scenario: there is no user with the FranceConnect id or FranceConnect email
        that is sent, so we create one
        """
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)
        self.assertFalse(User.objects.filter(username=fc_user_data.username).exists())
        self.assertFalse(User.objects.filter(email=fc_user_data.email).exists())
        user, created = fc_user_data.create_or_update_user()
        self.assertTrue(created)
        self.assertEqual(user.last_name, FC_USERINFO["family_name"])
        self.assertEqual(user.first_name, FC_USERINFO["given_name"])
        self.assertEqual(user.phone, FC_USERINFO["phone_number"])
        self.assertEqual(user.birthdate, datetime.date.fromisoformat(FC_USERINFO["birthdate"]))
        self.assertEqual(user.address_line_1, FC_USERINFO["address"]["street_address"])
        self.assertEqual(user.post_code, FC_USERINFO["address"]["postal_code"])
        self.assertEqual(user.city, FC_USERINFO["address"]["locality"])

        self.assertEqual(user.external_data_source_history[0]["source"], "FC")
        self.assertEqual(user.identity_provider, IdentityProvider.FRANCE_CONNECT)
        self.assertTrue(user.is_job_seeker)

        # Update user
        fc_user_data.last_name = "DUPUIS"
        user, created = fc_user_data.create_or_update_user()
        self.assertFalse(created)
        self.assertEqual(user.last_name, "DUPUIS")
        self.assertEqual(user.identity_provider, IdentityProvider.FRANCE_CONNECT)

    def test_create_django_user_optional_fields(self):
        fc_info = FC_USERINFO | {
            "given_name": "",
            "family_name": "",
            "birthdate": "",
            "phone_number": "",
            "address": {
                "street_address": "",
                "postal_code": "",
                "locality": "",
            },
        }
        fc_user_data = FranceConnectUserData.from_user_info(fc_info)
        user, created = fc_user_data.create_or_update_user()
        self.assertTrue(created)
        self.assertFalse(user.first_name)
        self.assertFalse(user.post_code)
        self.assertFalse(user.birthdate)
        self.assertFalse(user.phone)
        self.assertFalse(user.address_line_1)
        self.assertFalse(user.post_code)

    def test_create_django_user_country_other_than_france(self):
        """
        Nominal scenario: there is no user with the FranceConnect id or FranceConnect email
        that is sent, so we create one
        """
        user_info = FC_USERINFO | {
            "address": {
                "country": "Colombia",
                "locality": "Granada",
                "postal_code": "",
                "street_address": "Parque central",
            },
        }
        fc_user_data = FranceConnectUserData.from_user_info(user_info)
        self.assertFalse(User.objects.filter(username=fc_user_data.username).exists())
        self.assertFalse(User.objects.filter(email=fc_user_data.email).exists())
        user, created = fc_user_data.create_or_update_user()
        self.assertTrue(created)
        self.assertEqual(user.last_name, FC_USERINFO["family_name"])
        self.assertEqual(user.first_name, FC_USERINFO["given_name"])
        self.assertEqual(user.external_data_source_history[0]["source"], "FC")
        self.assertEqual(user.identity_provider, IdentityProvider.FRANCE_CONNECT)
        self.assertEqual(user.address_line_1, "")
        self.assertEqual(user.post_code, "")
        self.assertEqual(user.city, "")

    def test_create_django_user_with_already_existing_fc_id(self):
        """
        If there already is an existing user with this FranceConnectId, we do not create it again,
        we use it and we update it
        """
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)
        UserFactory(
            username=fc_user_data.username,
            last_name="will_be_forgotten",
            identity_provider=IdentityProvider.FRANCE_CONNECT,
        )
        user, created = fc_user_data.create_or_update_user()
        self.assertFalse(created)
        self.assertEqual(user.last_name, FC_USERINFO["family_name"])
        self.assertEqual(user.first_name, FC_USERINFO["given_name"])
        self.assertEqual(user.external_data_source_history[0]["source"], "FC")
        self.assertEqual(user.identity_provider, IdentityProvider.FRANCE_CONNECT)

    def test_create_django_user_with_already_existing_fc_id_but_from_other_sso(self):
        """
        If there already is an existing user with this FranceConnectId, but it comes from another SSO.
        The email is also different, so it will crash while trying to create a new user.
        """
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)
        UserFactory(
            username=fc_user_data.username,
            last_name="will_be_forgotten",
            identity_provider=IdentityProvider.DJANGO,
            email="random@email.com",
        )
        with self.assertRaises(ValidationError):
            fc_user_data.create_or_update_user()

    def test_create_django_user_with_already_existing_fc_email_django(self):
        """
        If there already is an existing user from Django with email FranceConnect sent us
        we use it and we update it
        """
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)
        UserFactory(email=fc_user_data.email, identity_provider=IdentityProvider.DJANGO)
        user, created = fc_user_data.create_or_update_user()
        self.assertFalse(created)
        self.assertEqual(user.last_name, FC_USERINFO["family_name"])
        self.assertEqual(user.first_name, FC_USERINFO["given_name"])
        self.assertEqual(user.username, FC_USERINFO["sub"])
        self.assertEqual(user.identity_provider, IdentityProvider.FRANCE_CONNECT)
        self.assertNotEqual(user.external_data_source_history, {})

    def test_create_django_user_with_already_existing_fc_email_other_sso(self):
        """
        If there already is an existing user with email FranceConnect sent us, we do not create it again,
        we use it but we do not update it
        """
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)
        UserFactory(email=fc_user_data.email, identity_provider=IdentityProvider.INCLUSION_CONNECT)
        user, created = fc_user_data.create_or_update_user()
        self.assertFalse(created)
        self.assertNotEqual(user.last_name, FC_USERINFO["family_name"])
        self.assertNotEqual(user.first_name, FC_USERINFO["given_name"])
        self.assertNotEqual(user.username, FC_USERINFO["sub"])
        # We did not fill this data using external data, so it is not set
        self.assertFalse(user.external_data_source_history)
        self.assertNotEqual(user.identity_provider, IdentityProvider.FRANCE_CONNECT)

    def test_create_or_update_user_raise_too_many_kind_exception(self):
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)

        for field in ["is_prescriber", "is_siae_staff", "is_labor_inspector"]:
            user = UserFactory(username=fc_user_data.username, email=fc_user_data.email, **{field: True})

            with self.assertRaises(TooManyKindsException):
                fc_user_data.create_or_update_user()

            user.delete()

    def test_callback_no_code(self):
        url = reverse("france_connect:callback")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_callback_no_state(self):
        url = reverse("france_connect:callback")
        response = self.client.get(url, data={"code": "123"})
        self.assertEqual(response.status_code, 302)

    def test_callback_invalid_state(self):
        url = reverse("france_connect:callback")
        response = self.client.get(url, data={"code": "123", "state": "000"})
        self.assertEqual(response.status_code, 302)

    @respx.mock
    def test_callback(self):
        mock_oauth_dance(self)
        self.assertEqual(User.objects.count(), 1)
        user = User.objects.get(email=FC_USERINFO["email"])
        self.assertEqual(user.first_name, FC_USERINFO["given_name"])
        self.assertEqual(user.last_name, FC_USERINFO["family_name"])
        self.assertEqual(user.username, FC_USERINFO["sub"])
        self.assertTrue(user.has_sso_provider)
        self.assertEqual(user.identity_provider, IdentityProvider.FRANCE_CONNECT)

    @respx.mock
    def test_callback_redirect_on_too_many_kind_exception(self):
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)

        for field in ["is_prescriber", "is_siae_staff", "is_labor_inspector"]:
            user = UserFactory(username=fc_user_data.username, email=fc_user_data.email, **{field: True})
            mock_oauth_dance(self, expected_route=f"login:{field[3:]}")
            user.delete()

    def test_logout_no_id_token(self):
        url = reverse("france_connect:logout")
        response = self.client.get(url + "?")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["message"], "Le paramètre « id_token » est manquant.")

    def test_logout(self):
        url = reverse("france_connect:logout")
        response = self.client.get(url, data={"id_token": "123"})
        expected_url = (
            f"{constants.FRANCE_CONNECT_ENDPOINT_LOGOUT}?id_token_hint=123&state=&"
            "post_logout_redirect_uri=http%3A%2F%2F127.0.0.1:8000%2F"
        )
        self.assertRedirects(response, expected_url, fetch_redirect_response=False)
