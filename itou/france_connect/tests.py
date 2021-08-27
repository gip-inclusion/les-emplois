from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import views as france_connect_views
from .models import FranceConnectState


class FranceConnectTest(TestCase):
    def test_state_delete(self):
        state = FranceConnectState.objects.create(csrf="foo")

        FranceConnectState.objects.cleanup()

        state.refresh_from_db()
        self.assertIsNotNone(state)

        # Set expired creation time for the state
        state.created_at = timezone.now() - settings.FRANCE_CONNECT_STATE_EXPIRATION * 2
        state.save()

        FranceConnectState.objects.cleanup()

        with self.assertRaises(FranceConnectState.DoesNotExist):
            state.refresh_from_db()

    def test_state_verification(self):
        csrf_signed = france_connect_views.state_new()
        self.assertTrue(france_connect_views.state_is_valid(csrf_signed))

    def test_authorize(self):
        url = reverse("france_connect:authorize")
        response = self.client.get(url, follow=False)
        # Don't use assertRedirects to avoid fetch
        self.assertTrue(
            response.url.startswith(settings.FRANCE_CONNECT_URL + settings.FRANCE_CONNECT_ENDPOINT_AUTHORIZE)
        )

    def test_create_user_from_user_data(self):
        user_data = {
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
        fc_user_data = france_connect_views.FranceConnectUserData(**france_connect_views.load_user_data(user_data))
        user, created = france_connect_views.create_or_update_user(fc_user_data)
        self.assertTrue(created)
        self.assertEqual(user.last_name, user_data["family_name"])
        self.assertEqual(user.first_name, user_data["given_name"])
        self.assertEqual(user.provider_json["last_name"]["source"], "fc")

        # Update user
        fc_user_data.last_name = "DUPUIS"
        user, created = france_connect_views.create_or_update_user(fc_user_data)
        self.assertFalse(created)
        self.assertEqual(user.last_name, "DUPUIS")
