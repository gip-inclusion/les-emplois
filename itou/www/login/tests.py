from django.test import TestCase
from django.urls import reverse


class ItouLoginTest(TestCase):
    def test_unauthorized_default_view(self):
        # ItouLogin overrides AllAuth default login view.
        # This parent class should be never be accessed directly.
        # Each child represents a login type (one per user kind).
        url = reverse("account_login")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)  # Forbidden

        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)  # Forbidden
