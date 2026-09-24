from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from tests.users.factories import PrescriberFactory


def test_home_anonymous(client, settings):
    settings.PLATEFORME_ACCUEIL_BASE_URL = "https://plateforme.accueil.fr"
    url = reverse("home:hp")
    response = client.get(url, follow=True)
    assertRedirects(response, reverse("search:home"))
    assertContains(
        response,
        'data-plateforme-accueil="https://plateforme.accueil.fr?host=localhost%3A8000&amp;no_forms=1"',
    )


def test_home_logged_in(client):
    client.force_login(PrescriberFactory())
    url = reverse("home:hp")
    response = client.get(url, follow=True)
    assertRedirects(response, reverse("dashboard:index"))
    assertContains(response, "Rechercher un emploi inclusif")
