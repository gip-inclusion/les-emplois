import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from tests.companies.factories import CompanyFactory


@pytest.mark.parametrize(
    "description,provided_support",
    [
        ("", ""),
        ("Mon activité", ""),
        ("", "Mon accompagnement"),
        ("Mon activité", "Mon accompagnement"),
    ],
)
def test_overview(client, description, provided_support):
    company = CompanyFactory(with_membership=True, description=description, provided_support=provided_support)
    client.force_login(company.members.get())
    response = client.get(reverse("companies_views:overview"))
    assertion = assertContains if description else assertNotContains
    assertion(response, "<h3>Son activité</h3>")
    assertion = assertContains if provided_support else assertNotContains
    assertion(response, "<h3>L'accompagnement proposé</h3>")
