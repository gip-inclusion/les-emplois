from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from tests.users.factories import PrescriberFactory


def test_home_anonymous(client):
    url = reverse("home:hp")
    response = client.get(url)
    response = client.get(url, follow=True)
    assertRedirects(response, reverse("search:employers_home"))
    assertContains(response, "Rechercher un emploi inclusif")


def test_home_logged_in(client):
    client.force_login(PrescriberFactory())
    url = reverse("home:hp")
    response = client.get(url, follow=True)
    assertContains(response, "Rechercher un emploi inclusif")
