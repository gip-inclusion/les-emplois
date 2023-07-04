from django.urls import reverse

from tests.utils.test import TestCase


class AllauthSignupTest(TestCase):
    def test_allauth_signup_url_override(self):
        """Ensure that the default allauth signup URL is overridden."""
        ALLAUTH_SIGNUP_URL = reverse("account_signup")
        assert ALLAUTH_SIGNUP_URL == "/accounts/signup/"
        response = self.client.get(ALLAUTH_SIGNUP_URL)
        assert response.status_code == 200
        self.assertTemplateUsed(response, "signup/signup.html")
        response = self.client.post(ALLAUTH_SIGNUP_URL, data={"foo": "bar"})
        assert response.status_code == 405
