from functools import partial
from urllib.parse import urlencode

import pytest
import respx
from django.urls import reverse
from django.utils.html import escape
from pytest_django.asserts import assertContains, assertRedirects

from itou.users.enums import IdentityProvider, UserKind
from tests.institutions.factories import LaborInspectorFactory
from tests.openid_connect.test import sso_parametrize
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    PrescriberFactory,
)


@sso_parametrize
@respx.mock
def test_prescriber_using_django_has_to_activate_sso_account(client, sso_setup):
    user = PrescriberFactory(identity_provider=IdentityProvider.DJANGO, email=sso_setup.oidc_userinfo["email"])
    client.force_login(user)
    url = reverse("dashboard:index")
    response = client.get(url, follow=True)
    activate_ic_account_url = reverse("dashboard:activate_ic_account")
    assertRedirects(response, activate_ic_account_url)
    params = {
        "user_kind": UserKind.PRESCRIBER,
        "previous_url": activate_ic_account_url,
        "user_email": user.email,
    }
    if sso_setup.identity_provider == IdentityProvider.INCLUSION_CONNECT:
        url = escape(f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}")
    else:
        url = escape(f"{reverse('pro_connect:authorize')}?{urlencode(params)}")
    assertContains(response, url + '"')
    response = sso_setup.mock_oauth_dance(
        client,
        UserKind.PRESCRIBER,
        previous_url=activate_ic_account_url,
    )
    user.refresh_from_db()
    assert user.identity_provider == sso_setup.identity_provider


@sso_parametrize
@respx.mock
def test_employer_using_django_has_to_activate_sso_account(client, sso_setup):
    user = EmployerFactory(
        with_company=True, identity_provider=IdentityProvider.DJANGO, email=sso_setup.oidc_userinfo["email"]
    )
    client.force_login(user)
    url = reverse("dashboard:index")
    response = client.get(url, follow=True)
    activate_ic_account_url = reverse("dashboard:activate_ic_account")
    assertRedirects(response, activate_ic_account_url)
    params = {
        "user_kind": UserKind.EMPLOYER,
        "previous_url": activate_ic_account_url,
        "user_email": user.email,
    }
    if sso_setup.identity_provider == IdentityProvider.INCLUSION_CONNECT:
        url = escape(f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}")
    else:
        url = escape(f"{reverse('pro_connect:authorize')}?{urlencode(params)}")
    assertContains(response, url + '"')
    response = sso_setup.mock_oauth_dance(
        client,
        UserKind.EMPLOYER,
        previous_url=activate_ic_account_url,
    )
    user.refresh_from_db()
    assert user.identity_provider == sso_setup.identity_provider


@pytest.mark.parametrize(
    "user_factory,is_redirected",
    [
        (ItouStaffFactory, True),
        (JobSeekerFactory, True),
        (PrescriberFactory, False),
        (partial(EmployerFactory, with_company=True), False),
        (partial(LaborInspectorFactory, membership=True), True),
    ],
)
def test_activate_ic_account_permissions(client, user_factory, is_redirected):
    client.force_login(user_factory())
    response = client.get(reverse("dashboard:activate_ic_account"))
    if is_redirected:
        assertRedirects(response, reverse("dashboard:index"), fetch_redirect_response=False)
    else:
        assert response.status_code == 200


def test_activate_ic_account_anonymous(client):
    response = client.get(reverse("dashboard:activate_ic_account"))
    assertRedirects(response, "/accounts/login/?next=/dashboard/activate_ic_account")
