import pytest
from django.urls import reverse, reverse_lazy
from pytest_django.asserts import assertContains, assertNotContains
from rest_framework.authtoken.models import Token

from tests.companies.factories import (
    CompanyFactory,
    CompanyMembershipFactory,
)


TOKEN_MENU_STR = "Accès aux APIs"
API_TOKEN_URL = reverse_lazy("dashboard:api_token")


@pytest.mark.ignore_unknown_variable_template_error("matomo_event_attrs")
def test_api_token_view_for_company_admin(client):
    employer = CompanyMembershipFactory().user
    client.force_login(employer)

    assert not Token.objects.exists()

    response = client.get(reverse("dashboard:index"))

    assertContains(response, TOKEN_MENU_STR)
    assertContains(response, API_TOKEN_URL)

    response = client.get(API_TOKEN_URL)
    assertContains(response, "Vous n'avez pas encore de token d'API")
    assertContains(response, "Créer un token d'API")

    response = client.post(API_TOKEN_URL)
    token = Token.objects.filter(user=employer).get()
    assertContains(response, token.key)
    assertContains(response, "Copier le token")

    # Check multi-posts
    response = client.post(API_TOKEN_URL)
    assert Token.objects.filter(user=employer).count() == 1


def test_api_token_view_for_non_company_admin(client):
    company = CompanyFactory(with_membership=True)
    employer = CompanyMembershipFactory(is_admin=False, company=company).user
    client.force_login(employer)

    assert not Token.objects.exists()

    response = client.get(reverse("dashboard:index"))

    assertNotContains(response, TOKEN_MENU_STR)
    assertNotContains(response, API_TOKEN_URL)

    response = client.get(API_TOKEN_URL)
    assert response.status_code == 403
