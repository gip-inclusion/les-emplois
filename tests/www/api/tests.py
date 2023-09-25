from django.conf import settings
from django.urls import reverse
from pytest_django.asserts import assertContains


def test_index(client):
    response = client.get(reverse("api:index"))
    assertContains(response, reverse("v1:redoc"))
    assertContains(response, f"mailto:{settings.API_EMAIL_CONTACT}")
