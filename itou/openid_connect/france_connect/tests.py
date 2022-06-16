import datetime

import httpx
import respx
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from itou.users.enums import IdentityProvider
from itou.users.factories import UserFactory
from itou.users.models import User

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


class FranceConnectTest(TestCase):
    def test_state_delete(self):
        state = FranceConnectState.objects.create(csrf="foo")

        FranceConnectState.objects.cleanup()

        state.refresh_from_db()
        self.assertIsNotNone(state)

        # Set expired creation time for the state
        state.created_at = timezone.now() - constants.FRANCE_CONNECT_STATE_EXPIRATION * 2
        state.save()

        FranceConnectState.objects.cleanup()

        with self.assertRaises(FranceConnectState.DoesNotExist):
            state.refresh_from_db()

    def test_state_verification(self):
        csrf_signed = FranceConnectState.create_signed_csrf_token()
        self.assertTrue(FranceConnectState.is_valid(csrf_signed))

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

        self.assertEqual(
            user.external_data_source_history["last_name"]["source"], IdentityProvider.FRANCE_CONNECT.value
        )
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
        self.assertEqual(
            user.external_data_source_history["last_name"]["source"], IdentityProvider.FRANCE_CONNECT.value
        )
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
        self.assertEqual(
            user.external_data_source_history["last_name"]["source"], IdentityProvider.FRANCE_CONNECT.value
        )
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

    def test_create_django_user_with_already_existing_fc_email(self):
        """
        If there already is an existing user with email FranceConnect sent us, we do not create it again,
        we use it but we do not update it
        """
        fc_user_data = FranceConnectUserData.from_user_info(FC_USERINFO)
        UserFactory(email=fc_user_data.email)
        user, created = fc_user_data.create_or_update_user()
        self.assertFalse(created)
        self.assertNotEqual(user.last_name, FC_USERINFO["family_name"])
        self.assertNotEqual(user.first_name, FC_USERINFO["given_name"])
        # We did not fill this data using external data, so it is not set
        self.assertFalse(user.external_data_source_history)
        self.assertNotEqual(user.identity_provider, IdentityProvider.FRANCE_CONNECT)

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
        url_fc_token = constants.FRANCE_CONNECT_ENDPOINT_TOKEN
        token_json = {"access_token": "7890123", "token_type": "Bearer", "expires_in": 60, "id_token": "123456"}
        respx.post(url_fc_token).mock(return_value=httpx.Response(200, json=token_json))

        url_fc_userinfo = constants.FRANCE_CONNECT_ENDPOINT_USERINFO
        respx.get(url_fc_userinfo).mock(return_value=httpx.Response(200, json=FC_USERINFO))

        csrf_signed = FranceConnectState.create_signed_csrf_token()
        url = reverse("france_connect:callback")
        response = self.client.get(url, data={"code": "123", "state": csrf_signed})
        self.assertEqual(response.status_code, 302)

    def test_logout_no_id_token(self):
        url = reverse("france_connect:logout")
        response = self.client.get(url + "?")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["message"], "Le paramètre « id_token » est manquant.")

    @respx.mock
    def test_logout(self):
        url = reverse("france_connect:logout")

        respx.post(url=constants.FRANCE_CONNECT_ENDPOINT_LOGOUT).respond(302)
        response = self.client.get(url, data={"id_token": "123"})
        self.assertEqual(response.status_code, 302)
