import datetime

import pytest
from django.urls import reverse
from itoutils.urls import add_url_params
from pytest_django.asserts import assertContains, assertRedirects, assertTemplateUsed

from itou.utils.legal_terms import get_latest_terms_datetime
from tests.users.factories import EmployerFactory, LaborInspectorFactory, PrescriberFactory


def _assert_redirect_to_legal_terms(response, *, next_url):
    expected_url = add_url_params(reverse("legal-terms"), {"next": next_url})
    assertRedirects(response, expected_url=expected_url, fetch_redirect_response=False)


def test_middleware_redirects_professional_when_not_accepted(client):
    user = EmployerFactory(membership=True, terms_accepted_at=None)
    client.force_login(user)

    target_url = reverse("dashboard:index")
    response = client.get(target_url)

    _assert_redirect_to_legal_terms(response, next_url=target_url)


def test_middleware_redirects_professional_with_outdated_terms(client):
    latest_terms_datetime = get_latest_terms_datetime()
    user = PrescriberFactory(membership=True, terms_accepted_at=latest_terms_datetime - datetime.timedelta(days=1))
    client.force_login(user)

    target_url = reverse("dashboard:index")
    response = client.get(target_url)

    _assert_redirect_to_legal_terms(response, next_url=target_url)


def test_middleware_allows_htmx_requests(client):
    user = EmployerFactory(membership=True, terms_accepted_at=None)
    client.force_login(user)
    response = client.get(reverse("dashboard:index"), headers={"HX-Request": "true"})
    assertTemplateUsed(response, "dashboard/dashboard.html")


def test_middleware_allows_post_requests(client):
    user = EmployerFactory(membership=True, terms_accepted_at=None)
    client.force_login(user)
    response = client.post(reverse("dashboard:index"))
    assertTemplateUsed(response, "dashboard/dashboard.html")


@pytest.mark.parametrize(
    "url_name, expected_content",
    [
        ("accessibility", "Accessibilité"),
        ("legal-notice", "Mentions légales"),
        ("legal-privacy", "Politique de confidentialité"),
        ("legal-terms", "Conditions Générales d'Utilisation"),  # no infinite redirection loop
    ],
)
def test_middleware_allows_static_public_pages(client, url_name, expected_content):
    user = EmployerFactory(membership=True, terms_accepted_at=None)
    client.force_login(user)
    response = client.get(reverse(url_name))
    assertContains(response, expected_content)


@pytest.mark.parametrize(
    "url_name",
    ["dashboard:edit_user_info", "dashboard:edit_user_notifications", "dashboard:edit_user_email"],
)
def test_account_pages_are_still_accessible(client, url_name):
    UserFactory = LaborInspectorFactory if "email" in url_name else EmployerFactory
    user = UserFactory(membership=True, terms_accepted_at=None)
    client.force_login(user)
    response = client.get(reverse(url_name))
    assert response.status_code == 200
