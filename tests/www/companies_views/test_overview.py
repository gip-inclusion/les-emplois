import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.companies.enums import CompanyKind
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


@pytest.mark.parametrize("is_searchable", [True, False])
def test_overview_public_card_link(client, is_searchable):
    company = CompanyFactory(with_membership=True, kind=CompanyKind.EI, is_searchable=is_searchable)
    client.force_login(company.members.get())
    response = client.get(reverse("companies_views:overview"))
    card_url = reverse("companies_views:card", kwargs={"company_pk": company.pk})
    notice = "Votre structure n’apparaît pas dans les résultats de recherche"
    if is_searchable:
        assertContains(response, f'href="{card_url}?back_url=')
        assertContains(response, "Voir la fiche publique")
        assertNotContains(response, notice)
    else:
        assertNotContains(response, card_url)
        assertNotContains(response, "Voir la fiche publique")
        assertContains(response, notice)
    assert client.get(card_url).status_code == (200 if is_searchable else 404)
