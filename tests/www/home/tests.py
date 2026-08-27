from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from itou.www.constants import REDIRECTED_FROM_OLD_DOMAIN_QUERY_PARAM
from tests.users.factories import PrescriberFactory


def test_home_anonymous(client):
    url = reverse("home:hp")
    response = client.get(url, follow=True)
    assertRedirects(response, reverse("search:home"))
    assertContains(response, 'data-plateforme-accueil="https://accueil.plateforme.inclusion.gouv.fr"')

    query = {REDIRECTED_FROM_OLD_DOMAIN_QUERY_PARAM: "1"}
    response = client.get(url, query_params=query)
    assertRedirects(response, reverse("search:home", query=query))


def test_home_logged_in(client):
    client.force_login(PrescriberFactory(membership=True))
    url = reverse("home:hp")
    response = client.get(url, follow=True)
    assertRedirects(response, reverse("dashboard:index"))
    assertContains(response, "Rechercher un emploi inclusif")

    query = {REDIRECTED_FROM_OLD_DOMAIN_QUERY_PARAM: "1"}
    response = client.get(url, query_params=query)
    assertRedirects(response, reverse("dashboard:index", query=query))
