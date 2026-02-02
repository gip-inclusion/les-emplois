import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.cities.models import City
from tests.companies.factories import CompanyFactory
from tests.utils.testing import parse_response_to_soup


@pytest.fixture
def di_settings(settings):
    settings.API_DATA_INCLUSION_WIDGET_TOKEN = "test-token"
    return settings


def test_dora_iframe_displayed_when_token_and_code_insee_available(client, di_settings):
    city = City.objects.create(
        name="Paris",
        slug="paris-75",
        department="75",
        coords=Point(2.347, 48.859),
        post_codes=["75001"],
        code_insee="75056",
    )
    company = CompanyFactory(with_membership=True, insee_city=city)

    url = reverse("companies_views:card", kwargs={"company_pk": company.pk})
    response = client.get(url)

    assertContains(response, "Découvrez l'offre d'insertion disponible sur votre territoire")
    iframe = parse_response_to_soup(response, selector="section[data-content-name='dora-di-banner'] iframe")
    assert "api.data.inclusion.gouv.fr/widget" in iframe["src"]
    assert "token=test-token" in iframe["src"]
    assert "code_commune=75056" in iframe["src"]


def test_dora_iframe_not_displayed_without_token(client, di_settings):
    di_settings.API_DATA_INCLUSION_WIDGET_TOKEN = None
    city = City.objects.create(
        name="Paris",
        slug="paris-75",
        department="75",
        coords=Point(2.347, 48.859),
        post_codes=["75001"],
        code_insee="75056",
    )
    company = CompanyFactory(with_membership=True, insee_city=city)

    url = reverse("companies_views:card", kwargs={"company_pk": company.pk})
    response = client.get(url)

    assertNotContains(response, "api.data.inclusion.gouv.fr/widget")


def test_dora_iframe_not_displayed_without_code_insee(client, di_settings):
    company = CompanyFactory(with_membership=True, insee_city=None)

    url = reverse("companies_views:card", kwargs={"company_pk": company.pk})
    response = client.get(url)

    assertNotContains(response, "api.data.inclusion.gouv.fr/widget")
