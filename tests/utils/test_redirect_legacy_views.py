import pytest
from django.urls import reverse
from pytest_django.asserts import assertRedirects

from tests.companies.factories import CompanyFactory


@pytest.mark.ignore_unknown_variable_template_error
def test_redirect_siae_views(client):
    company = CompanyFactory()

    url = f"/siae/{company.pk}/card"
    response = client.get(url)
    assertRedirects(response, reverse("companies_views:card", kwargs={"siae_id": company.pk}), status_code=301)
