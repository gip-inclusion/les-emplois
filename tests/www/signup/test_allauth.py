from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed


def test_allauth_signup_url_override(client):
    """Ensure that the default allauth signup URL is overridden."""
    ALLAUTH_SIGNUP_URL = reverse("account_signup")
    assert ALLAUTH_SIGNUP_URL == "/accounts/signup/"
    response = client.get(ALLAUTH_SIGNUP_URL)
    assert response.status_code == 200
    assertTemplateUsed(response, "signup/signup.html")
    response = client.post(ALLAUTH_SIGNUP_URL, data={"foo": "bar"})
    assert response.status_code == 405
