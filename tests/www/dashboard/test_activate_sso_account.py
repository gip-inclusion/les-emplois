from urllib.parse import urlencode

import pytest
from django.urls import reverse
from django.utils.html import escape
from pytest_django.asserts import assertContains, assertRedirects

from itou.users.enums import IdentityProvider
from tests.institutions.factories import LaborInspectorFactory
from tests.users.factories import EmployerFactory, ItouStaffFactory, JobSeekerFactory, PrescriberFactory


def test_prescriber_using_django_has_to_activate_sso_account(client, pro_connect):
    user = PrescriberFactory(
        identity_provider=IdentityProvider.DJANGO,
        email=pro_connect.oidc_userinfo["email"],
    )
    client.force_login(user)
    url = reverse("dashboard:index")
    response = client.get(url, follow=True)
    activate_pro_connect_account_url = reverse("dashboard:activate_pro_connect_account")
    assertRedirects(response, activate_pro_connect_account_url)
    params = {
        "previous_url": activate_pro_connect_account_url,
        "user_email": user.email,
    }
    url = escape(f"{reverse('pro_connect:authorize')}?{urlencode(params)}")
    assertContains(response, url + '"')
    response = pro_connect.mock_oauth_dance(
        client,
        previous_url=activate_pro_connect_account_url,
    )
    user.refresh_from_db()
    assert user.identity_provider == IdentityProvider.PRO_CONNECT


def test_employer_using_django_has_to_activate_sso_account(client, pro_connect):
    user = EmployerFactory(identity_provider=IdentityProvider.DJANGO, email=pro_connect.oidc_userinfo["email"])
    client.force_login(user)
    url = reverse("dashboard:index")
    response = client.get(url, follow=True)
    activate_pro_connect_account_url = reverse("dashboard:activate_pro_connect_account")
    assertRedirects(response, activate_pro_connect_account_url)
    params = {
        "previous_url": activate_pro_connect_account_url,
        "user_email": user.email,
    }
    url = escape(f"{reverse('pro_connect:authorize')}?{urlencode(params)}")
    assertContains(response, url + '"')
    response = pro_connect.mock_oauth_dance(
        client,
        previous_url=activate_pro_connect_account_url,
    )
    user.refresh_from_db()
    assert user.identity_provider == IdentityProvider.PRO_CONNECT


@pytest.mark.parametrize(
    "user_factory,is_redirected",
    [
        (ItouStaffFactory, True),
        (JobSeekerFactory, True),
        (PrescriberFactory, False),
        (EmployerFactory, False),
        (LaborInspectorFactory, False),
    ],
    ids=["staff", "jobseeker", "prescriber", "employer", "labor_inspector"],
)
def test_activate_pro_connect_account_permissions(client, user_factory, is_redirected):
    client.force_login(user_factory())
    response = client.get(reverse("dashboard:activate_pro_connect_account"))
    if is_redirected:
        assertRedirects(response, reverse("dashboard:index"), fetch_redirect_response=False)
    else:
        assert response.status_code == 200


def test_activate_pro_connect_account_anonymous(client):
    response = client.get(reverse("dashboard:activate_pro_connect_account"))
    assertRedirects(response, "/accounts/login/?next=/dashboard/activate-pro-connect-account")
