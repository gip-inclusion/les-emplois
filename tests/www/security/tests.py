from django.urls import reverse
from pytest_django.asserts import assertRedirects


def test_redirects(client):
    response = client.get(reverse("security-txt"))
    assertRedirects(response, "https://inclusion.gouv.fr/.well-known/security.txt", fetch_redirect_response=False)
