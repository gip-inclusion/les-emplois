from django.urls import reverse
from pytest_django.asserts import assertContains

from tests.users.factories import PrescriberFactory


def test_home_anonymous(client, settings):
    settings.PLATEFORME_ACCUEIL_BASE_URL = "https://plateforme.accueil.fr"
    url = reverse("home:hp")
    response = client.get(url)
    assertContains(
        response,
        'data-plateforme-accueil="https://plateforme.accueil.fr?host=localhost%3A8000"',
    )


def test_home_logged_in(client):
    client.force_login(PrescriberFactory())
    url = reverse("home:hp")
    response = client.get(url, follow=True)
    assertContains(response, "Rechercher un emploi inclusif")
