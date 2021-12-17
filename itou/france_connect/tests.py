import httpx
import respx
from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..users.factories import UserFactory
from ..users.models import User
from . import models as france_connect_models, views as france_connect_views


FRANCE_CONNECT_USERINFO = {
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
        state = france_connect_models.FranceConnectState.objects.create(csrf="foo")

        france_connect_models.FranceConnectState.objects.cleanup()

        state.refresh_from_db()
        self.assertIsNotNone(state)

        # Set expired creation time for the state
        state.created_at = timezone.now() - settings.FRANCE_CONNECT_STATE_EXPIRATION * 2
        state.save()

        france_connect_models.FranceConnectState.objects.cleanup()

        with self.assertRaises(france_connect_models.FranceConnectState.DoesNotExist):
            state.refresh_from_db()

    def test_state_verification(self):
        csrf_signed = france_connect_views.state_new()
        self.assertTrue(france_connect_views.state_is_valid(csrf_signed))

    def test_authorize(self):
        url = reverse("france_connect:authorize")
        response = self.client.get(url, follow=False)
        # Don't use assertRedirects to avoid fetch
        self.assertTrue(
            response.url.startswith(settings.FRANCE_CONNECT_BASE_URL + settings.FRANCE_CONNECT_ENDPOINT_AUTHORIZE)
        )

    def test_create_user_from_user_data(self):
        """
        Nominal scenario: there is no user with the FranceConnect id or FranceConnect email
        that is sent, so we create one
        """
        user_data = FRANCE_CONNECT_USERINFO
        fc_user_data = france_connect_models.FranceConnectUserData(**france_connect_models.load_user_data(user_data))
        self.assertFalse(User.objects.filter(username=fc_user_data.username).exists())
        self.assertFalse(User.objects.filter(email=fc_user_data.email).exists())
        user, created = france_connect_models.create_or_update_user(fc_user_data)
        self.assertTrue(created)
        self.assertEqual(user.last_name, user_data["family_name"])
        self.assertEqual(user.first_name, user_data["given_name"])
        self.assertEqual(user.external_data_source_history["last_name"]["source"], "franceconnect")

        # Update user
        fc_user_data.last_name = "DUPUIS"
        user, created = france_connect_models.create_or_update_user(fc_user_data)
        self.assertFalse(created)
        self.assertEqual(user.last_name, "DUPUIS")

    def test_create_user_from_user_data_with_already_existing_fc_id(self):
        """
        If there already is an existing user with this FranceConnectId, we do not create it again,
        we use it and we update it
        """
        user_data = FRANCE_CONNECT_USERINFO
        fc_user_data = france_connect_models.FranceConnectUserData(**france_connect_models.load_user_data(user_data))
        UserFactory(username=fc_user_data.username, last_name="will_be_forgotten")
        user, created = france_connect_models.create_or_update_user(fc_user_data)
        self.assertFalse(created)
        self.assertEqual(user.last_name, user_data["family_name"])
        self.assertEqual(user.first_name, user_data["given_name"])
        self.assertEqual(user.external_data_source_history["last_name"]["source"], "franceconnect")

    def test_create_user_from_user_data_with_already_existing_fc_email(self):
        """
        If there already is an existing user with email FranceConnect sent us, we do not create it again,
        we use it but we do not update it
        """
        user_data = FRANCE_CONNECT_USERINFO
        fc_user_data = france_connect_models.FranceConnectUserData(**france_connect_models.load_user_data(user_data))
        UserFactory(email=fc_user_data.email)
        user, created = france_connect_models.create_or_update_user(fc_user_data)
        self.assertFalse(created)
        self.assertNotEqual(user.last_name, user_data["family_name"])
        self.assertNotEqual(user.first_name, user_data["given_name"])
        # We did not fill this data using external data, so it is not set
        self.assertIsNone(user.external_data_source_history)

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
        url_fc_token = settings.FRANCE_CONNECT_BASE_URL + settings.FRANCE_CONNECT_ENDPOINT_TOKEN
        token_json = {"access_token": "7890123", "token_type": "Bearer", "expires_in": 60, "id_token": "123456"}
        respx.post(url_fc_token).mock(return_value=httpx.Response(200, json=token_json))

        url_fc_userinfo = settings.FRANCE_CONNECT_BASE_URL + settings.FRANCE_CONNECT_ENDPOINT_USERINFO
        respx.get(url_fc_userinfo).mock(return_value=httpx.Response(200, json=FRANCE_CONNECT_USERINFO))

        csrf_signed = france_connect_views.state_new()
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

        respx.post(url=settings.FRANCE_CONNECT_BASE_URL + settings.FRANCE_CONNECT_ENDPOINT_LOGOUT).respond(302)
        response = self.client.get(url, data={"id_token": "123"})
        self.assertEqual(response.status_code, 302)
