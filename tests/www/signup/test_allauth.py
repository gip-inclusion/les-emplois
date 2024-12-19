from django.urls import reverse
from pytest_django.asserts import assertRedirects


def test_allauth_signup_url_redirect(client):
    ALLAUTH_SIGNUP_URL = reverse("account_signup")
    assert ALLAUTH_SIGNUP_URL == "/accounts/signup/"
    response = client.get(ALLAUTH_SIGNUP_URL)
    assertRedirects(response, reverse("signup:choose_user_kind"))
