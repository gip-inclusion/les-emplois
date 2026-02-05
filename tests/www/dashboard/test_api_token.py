from django.urls import reverse, reverse_lazy
from pytest_django.asserts import assertContains, assertNotContains
from rest_framework.authtoken.models import Token

from tests.companies.factories import (
    CompanyFactory,
    CompanyMembershipFactory,
)


TOKEN_MENU_STR = "Accès aux APIs"
API_TOKEN_URL = reverse_lazy("dashboard:api_token")


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


def test_api_token_view_for_mixed_admin_nonadmin_company(client):
    admin_company = CompanyFactory(with_membership=True)
    employer = CompanyMembershipFactory(is_admin=True, company=admin_company).user
    non_admin_company = CompanyMembershipFactory(user=employer, is_admin=False).company
    client.force_login(employer)

    response = client.post(API_TOKEN_URL)

    assertContains(
        response,
        f"""<tr>
              <th scope="row">{admin_company.name}</th>
              <td>{admin_company.uid}</td>
              <td>oui</td>
            </tr>""",
        html=True,
    )
    assertContains(
        response,
        f"""<tr>
              <th scope="row">{non_admin_company.name}</th>
              <td>{non_admin_company.uid}</td>
              <td>non</td>
            </tr>""",
        html=True,
    )
