from django.urls import reverse
from pytest_django.asserts import assertRedirects

from tests.companies.factories import SiaeFactory


def test_redirect_siae_views(client):
    siae = SiaeFactory()

    url = f"/siae/{siae.pk}/card"
    response = client.get(url)
    assertRedirects(response, reverse("companies_views:card", kwargs={"siae_id": siae.pk}), status_code=301)
