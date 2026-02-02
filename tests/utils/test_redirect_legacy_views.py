from django.urls import reverse
from pytest_django.asserts import assertRedirects

from tests.companies.factories import CompanyFactory


def test_redirect_siae_views(client):
    company = CompanyFactory()

    url = f"/siae/{company.pk}/card"
    response = client.get(url)
    assertRedirects(response, reverse("companies_views:card", kwargs={"company_pk": company.pk}), status_code=301)
