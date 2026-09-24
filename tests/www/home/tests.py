from django.urls import reverse
from pytest_django.asserts import assertContains

from tests.users.factories import PrescriberFactory
from tests.utils.testing import parse_response_to_soup


def test_home_anonymous(client, settings, snapshot):
    settings.PLATEFORME_ACCUEIL_BASE_URL = "https://plateforme.accueil.fr"
    url = reverse("home:hp")
    response = client.get(url)
    assertContains(
        response,
        'data-plateforme-accueil="https://plateforme.accueil.fr?host=localhost%3A8000&amp;no_forms=1"',
    )
    soup = parse_response_to_soup(response)
    [tabButton, tabContent] = soup.find_all(class_="active")
    assert list(tabButton.stripped_strings) == ["Un emploi inclusif", "Emploi inclusif"]
    assert tabContent.prettify() == snapshot


def test_home_logged_in(client):
    client.force_login(PrescriberFactory())
    url = reverse("home:hp")
    response = client.get(url, follow=True)
    assertContains(response, "Rechercher un emploi inclusif")
