from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import jwt
import respx
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import classproperty
from pytest_django.asserts import assertContains, assertRedirects

from itou.openid_connect.pro_connect import constants
from itou.users.enums import IdentityProvider
from itou.utils.urls import add_url_params
from tests.utils.test import reload_module


OIDC_USERINFO = {
    "given_name": "Michel",
    "usual_name": "AUDIARD",
    "email": "michel@lestontons.fr",
    "sub": "af6b26f9-85cd-484e-beb9-bea5be13e30f",
}

OIDC_USERINFO_FT_WITH_SAFIR = OIDC_USERINFO | {
    "email": "michel@francetravail.fr",
    "custom": {"structureTravail": "95021"},
}


# Make sure this decorator is before test definition, not here.
# @respx.mock
def mock_oauth_dance(
    client,
    user_kind,
    previous_url=None,
    next_url=None,
    expected_redirect_url=None,
    user_email=None,
    user_info_email=None,
    channel=None,
    register=True,
    other_client=None,
    oidc_userinfo=None,
):
    assert user_kind, "Letting this filed empty is not allowed"
    # Authorize params depend on user kind.
    authorize_params = {
        "user_kind": user_kind,
        "previous_url": previous_url,
        "next_url": next_url,
        "user_email": user_email,
        "channel": channel,
        "register": register,
    }
    authorize_params = {k: v for k, v in authorize_params.items() if v}

    # Calling this view is mandatory to start a new session.
    authorize_url = f"{reverse('pro_connect:authorize')}?{urlencode(authorize_params)}"
    response = client.get(authorize_url)
    assert response.url.startswith(constants.PRO_CONNECT_ENDPOINT_AUTHORIZE)

    token_json = {"access_token": "access_token", "token_type": "Bearer", "expires_in": 60, "id_token": "123456"}
    respx.post(constants.PRO_CONNECT_ENDPOINT_TOKEN).mock(return_value=httpx.Response(200, json=token_json))

    user_info = oidc_userinfo or OIDC_USERINFO.copy()
    if user_info_email:
        user_info["email"] = user_info_email
    # Put a issued at in the future to ensure we don't check it
    user_info = user_info | {"aud": constants.PRO_CONNECT_CLIENT_ID, "iat": timezone.now() + relativedelta(hours=1)}
    user_info_jwt = jwt.encode(payload=user_info, key=constants.PRO_CONNECT_CLIENT_SECRET, algorithm="HS256")
    respx.get(constants.PRO_CONNECT_ENDPOINT_USERINFO).mock(return_value=httpx.Response(200, content=user_info_jwt))

    state = client.session[constants.PRO_CONNECT_SESSION_KEY]["state"]
    url = reverse("pro_connect:callback")
    callback_client = other_client or client
    response = callback_client.get(url, data={"code": "123", "state": state})
    # If a expected_redirect_url was provided, check it redirects there
    # If not, the default redirection is next_url if provided, or welcoming_tour for new users
    expected = expected_redirect_url or next_url or reverse("welcoming_tour:index")
    assertRedirects(response, expected, fetch_redirect_response=False)
    return response


def assert_and_mock_forced_logout(client, response, expected_redirect_url=reverse("search:employers_home")):
    assertRedirects(response, reverse("pro_connect:logout") + "?token=123456", fetch_redirect_response=False)
    response = client.get(response.url)
    assert response.url.startswith(constants.PRO_CONNECT_ENDPOINT_LOGOUT)
    query_params = parse_qs(urlparse(response.url).query)
    post_logout_redirect_uri = query_params["post_logout_redirect_uri"][0]
    state = query_params["state"][0]
    local_url = post_logout_redirect_uri.split(settings.ITOU_FQDN)[1]
    assert local_url == reverse("pro_connect:logout_callback")
    response = client.get(add_url_params(local_url, {"state": state}))
    assertRedirects(response, expected_redirect_url)
    return response


TEST_SETTINGS = {
    "PRO_CONNECT_BASE_URL": "https://pro.connect.fake",
    "PRO_CONNECT_CLIENT_ID": "PC_CLIENT_ID_123",
    "PRO_CONNECT_CLIENT_SECRET": "PC_CLIENT_SECRET_123",
    "PRO_CONNECT_FT_IDP_HINT": "xxxxxx",
}


class pro_connect_setup:
    oidc_userinfo = OIDC_USERINFO
    oidc_userinfo_with_safir = OIDC_USERINFO_FT_WITH_SAFIR
    mock_oauth_dance = mock_oauth_dance
    assert_and_mock_forced_logout = assert_and_mock_forced_logout
    identity_provider = IdentityProvider.PRO_CONNECT
    session_key = constants.PRO_CONNECT_SESSION_KEY

    def __init__(self):
        self.context_managers = [override_settings(**TEST_SETTINGS), reload_module(constants)]

    def __enter__(self):
        for context_manager in self.context_managers:
            context_manager.__enter__()

    def __exit__(self, *args, **kwargs):
        for context_manager in self.context_managers:
            context_manager.__exit__(*args, **kwargs)

    @classmethod
    def assertContainsButton(cls, response):
        assertContains(response, 'class="proconnect-button"')

    @classproperty
    def authorize_url(cls):
        return reverse("pro_connect:authorize")

    @classproperty
    def logout_url(cls):
        return reverse("pro_connect:logout")
