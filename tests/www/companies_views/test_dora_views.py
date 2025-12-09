from django.contrib.gis.geos import Point
from django.urls import reverse

from itou.cities.models import City
from tests.companies.factories import CompanyFactory
from tests.utils.testing import parse_response_to_soup


def test_dora_iframe_displayed_when_token_and_code_insee_available(client, settings):
    settings.API_DATA_INCLUSION_WIDGET_TOKEN = "test-token"
    city = City.objects.create(
        name="Paris",
        slug="paris-75",
        department="75",
        coords=Point(2.347, 48.859),
        post_codes=["75001"],
        code_insee="75056",
    )
    company = CompanyFactory(with_membership=True, insee_city=city)

    url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
    response = client.get(url)

    assert response.status_code == 200
    soup = parse_response_to_soup(response, selector="section[data-content-name='dora-di-banner']")

    assert soup is not None
    assert "Découvrez l'offre d'insertion" in soup.get_text()

    iframe = soup.find("iframe")
    assert iframe is not None
    assert "api.data.inclusion.gouv.fr/widget" in iframe.get("src", "")
    assert "test-token" in iframe.get("src", "")
    assert "75056" in iframe.get("src", "")


def test_dora_iframe_not_displayed_without_token(client, settings):
    settings.API_DATA_INCLUSION_WIDGET_TOKEN = None
    city = City.objects.create(
        name="Paris",
        slug="paris-75",
        department="75",
        coords=Point(2.347, 48.859),
        post_codes=["75001"],
        code_insee="75056",
    )
    company = CompanyFactory(with_membership=True, insee_city=city)

    url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
    response = client.get(url)

    assert response.status_code == 200
    soup = parse_response_to_soup(response)

    section = soup.find("section", {"data-content-name": "dora-di-banner"})
    assert section is None


def test_dora_iframe_not_displayed_without_code_insee(client, settings):
    settings.API_DATA_INCLUSION_WIDGET_TOKEN = "test-token"
    company = CompanyFactory(with_membership=True, insee_city=None)

    url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
    response = client.get(url)

    assert response.status_code == 200
    soup = parse_response_to_soup(response)

    section = soup.find("section", {"data-content-name": "dora-di-banner"})
    assert section is None
