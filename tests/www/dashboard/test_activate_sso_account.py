from urllib.parse import urlencode

import pytest
from django.urls import reverse
from django.utils.html import escape
from django_otp.oath import TOTP
from itoutils.urls import add_url_params
from pytest_django.asserts import assertContains, assertRedirects

from itou.users.enums import IdentityProvider
from tests.institutions.factories import LaborInspectorFactory
from tests.otp.factories import ItouTOTPDeviceFactory
from tests.users.factories import (
    DEFAULT_PASSWORD,
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    PrescriberFactory,
)


@pytest.mark.parametrize("user_factory", [PrescriberFactory, EmployerFactory, LaborInspectorFactory, ItouStaffFactory])
def test_activate_sso_account(client, pro_connect, user_factory, settings):
    settings.FORCE_PROCONNECT_LOGIN_FOR_ADMIN = True

    oidc_userinfo = pro_connect.oidc_userinfo.copy()
    if user_factory == ItouStaffFactory:
        oidc_userinfo["email"] = "john.doe@inclusion.gouv.fr"

    user = user_factory(
        identity_provider=IdentityProvider.DJANGO,
        email=oidc_userinfo["email"],
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
        oidc_userinfo=oidc_userinfo,
    )
    user.refresh_from_db()
    assert user.identity_provider == IdentityProvider.PRO_CONNECT


@pytest.mark.parametrize("user_factory", [PrescriberFactory, EmployerFactory, LaborInspectorFactory, ItouStaffFactory])
def test_activate_sso_account_with_mfa(client, pro_connect, user_factory, settings):
    settings.FORCE_PROCONNECT_LOGIN_FOR_ADMIN = True
    settings.FORCE_PROCONNECT_LOGIN_FOR_PRO = True
    settings.REQUIRE_MFA_FOR_PROS = True
    settings.REQUIRE_OTP_FOR_STAFF = True

    oidc_userinfo = pro_connect.oidc_userinfo.copy()
    if user_factory == ItouStaffFactory:
        oidc_userinfo["email"] = "john.doe@inclusion.gouv.fr"

    user = user_factory(
        identity_provider=IdentityProvider.DJANGO,
        email=oidc_userinfo["email"],
        has_completed_welcoming_tour=True,
        with_verified_email=True,
    )
    device = ItouTOTPDeviceFactory(name="1", user=user)

    pre_login_url = reverse("account_login")
    login_url = add_url_params(reverse("login:existing_user"), {"back_url": pre_login_url})
    verify_otp_url = reverse("otp_views:verify_otp")

    response = client.post(pre_login_url, {"email": user.email})
    assertRedirects(response, login_url)

    # The user has a TOTP device and should use it
    form_data = {
        "login": user.email,
        "password": DEFAULT_PASSWORD,
    }
    response = client.post(login_url, data=form_data, follow=True)
    next_url = add_url_params(verify_otp_url, {"next": reverse("dashboard:index")})
    assertRedirects(response, next_url)

    # They enter their TOTP code
    response = client.post(verify_otp_url, data={"otp_token": TOTP(device.bin_key).token()}, follow=True)
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
        oidc_userinfo=oidc_userinfo,
        expected_redirect_url=reverse("dashboard:index"),
    )
    user.refresh_from_db()
    assert user.identity_provider == IdentityProvider.PRO_CONNECT


@pytest.mark.parametrize(
    "user_factory,is_redirected",
    [
        (ItouStaffFactory, False),
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
