from django.contrib import messages
from django.urls import reverse, reverse_lazy
from pytest_django.asserts import assertContains, assertMessages, assertNotContains
from rest_framework.authtoken.models import Token

from tests.companies.factories import (
    CompanyFactory,
    CompanyMembershipFactory,
)
from tests.utils.testing import parse_response_to_soup, pretty_indented


TOKEN_MENU_STR = "Accès aux APIs"
API_TOKEN_URL = reverse_lazy("dashboard:api_token")


def test_api_token_view_for_company_admin(client, mailoutbox):
    employer = CompanyMembershipFactory().user
    client.force_login(employer)

    assert not Token.objects.exists()

    response = client.get(reverse("dashboard:index"))

    assertContains(response, TOKEN_MENU_STR)
    assertContains(response, API_TOKEN_URL)

    response = client.get(API_TOKEN_URL)
    assertContains(response, "Vous n’avez pas encore de token d’API")
    assertContains(response, "Créer un token d’API")

    user_ip_address = "123.45.67.89"
    response = client.post(API_TOKEN_URL, REMOTE_ADDR=user_ip_address)
    token = Token.objects.filter(user=employer).get()
    assertContains(response, token.key)
    assertContains(response, "Il est indispensable de le copier afin de le sauvegarder")
    assertMessages(
        response,
        [messages.Message(messages.SUCCESS, "Votre nouveau token a été créé avec succès.", extra_tags="toast")],
    )
    [email] = mailoutbox
    assert email.subject.endswith("Génération d’un nouveau token d’API sur les Emplois de l'inclusion")
    assert user_ip_address in email.body

    # Check multi-posts
    response = client.post(API_TOKEN_URL)
    assert Token.objects.filter(user=employer).count() == 1
    # No new mail is sent
    assert len(mailoutbox) == 1
    # Token is not present on refresh
    assertNotContains(response, token.key)


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


def test_api_token_view_for_mixed_admin_nonadmin_company(client, snapshot):
    admin_company = CompanyFactory(
        with_membership=True, name="Job insertion 90", brand="", uid="42975396-5d50-4dea-aa38-ca498c679672"
    )
    employer = CompanyMembershipFactory(is_admin=True, company=admin_company).user
    CompanyMembershipFactory(
        user=employer,
        is_admin=False,
        company__name="Non affiché",
        company__brand="Emploi CAPITAL Mais pas que",
        company__uid="42975396-5d50-4dea-aa38-ca498c679673",
    ).company
    client.force_login(employer)

    response = client.post(API_TOKEN_URL)
    token = Token.objects.get()
    assert (
        pretty_indented(parse_response_to_soup(response, "#main")).replace(str(token), "[Token of user]") == snapshot
    )


def test_api_token_view_regenerate(client, mailoutbox):
    employer = CompanyMembershipFactory().user
    client.force_login(employer)

    assert not Token.objects.exists()

    response = client.post(API_TOKEN_URL)
    token = Token.objects.filter(user=employer).get()
    assertContains(response, token.key)
    assertContains(response, "Il est indispensable de le copier afin de le sauvegarder")
    [email] = mailoutbox
    assert email.subject.endswith("Génération d’un nouveau token d’API sur les Emplois de l'inclusion")

    response = client.post(API_TOKEN_URL, {"action": "regenerate"})
    # Previous token has been deleted
    assert not Token.objects.filter(key=token.key).exists()

    new_token = Token.objects.filter(user=employer).get()
    assert len(mailoutbox) == 2
    new_email = mailoutbox[-1]
    assert new_email.subject.endswith("Génération d’un nouveau token d’API sur les Emplois de l'inclusion")
    assertContains(response, new_token.key)
    assertContains(response, "Il est indispensable de le copier afin de le sauvegarder")
    assertMessages(
        response, [messages.Message(messages.SUCCESS, "Votre token a été regénéré avec succès.", extra_tags="toast")]
    )

    # Token is not present on refresh
    response = client.get(API_TOKEN_URL)
    assertNotContains(response, token.key)
