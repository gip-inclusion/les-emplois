import httpx
import pytest
from django.core.exceptions import ImproperlyConfigured

from itou.utils.apis import rdv_service_public
from itou.utils.mocks.rdv_service_public import (
    RDV_SERVICE_PUBLIC_AGENT_BODY,
    RDV_SERVICE_PUBLIC_RDV_PLAN_BODY,
    RDV_SERVICE_PUBLIC_TOKEN_BODY,
)


BASE_URL = "https://rdv-service-public.fake"
TOKEN_URL = f"{BASE_URL}/oauth/token"
ME_URL = f"{BASE_URL}/api/v1/agents/me"
RDV_PLANS_URL = f"{BASE_URL}/api/v1/rdv_plans"
REDIRECT_URI = "http://localhost:8000/rdv-service-public/oauth/callback"
TOKEN_DATA = rdv_service_public.TokenData(access_token="access-token", refresh_token="refresh-token", expires_in=7200)


@pytest.fixture(autouse=True)
def rdvsp_settings(settings):
    settings.RDV_SERVICE_PUBLIC_BASE_URL = BASE_URL
    settings.RDV_SERVICE_PUBLIC_CLIENT_ID = "client-id"
    settings.RDV_SERVICE_PUBLIC_CLIENT_SECRET = "S3cr3t!"
    return settings


def test_improperly_configured(rdvsp_settings):
    rdvsp_settings.RDV_SERVICE_PUBLIC_CLIENT_SECRET = ""
    with pytest.raises(ImproperlyConfigured):
        rdv_service_public.get_oauth_client()
    with pytest.raises(ImproperlyConfigured):
        rdv_service_public.get_api_client("access-token")


def test_get_authorize_url():
    url = rdv_service_public.get_oauth_client().get_authorize_url(redirect_uri=REDIRECT_URI, state="random-state")
    assert url == (
        "https://rdv-service-public.fake/oauth/authorize?client_id=client-id"
        "&redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Frdv-service-public%2Foauth%2Fcallback"
        "&response_type=code&scope=write&state=random-state"
    )


def test_get_token(respx_mock):
    respx_mock.post(
        TOKEN_URL,
        data={
            "client_id": "client-id",
            "client_secret": "S3cr3t!",
            "grant_type": "authorization_code",
            "code": "the-code",
            "redirect_uri": REDIRECT_URI,
        },
    ).respond(200, json=RDV_SERVICE_PUBLIC_TOKEN_BODY)
    token = rdv_service_public.get_oauth_client().get_token(code="the-code", redirect_uri=REDIRECT_URI)
    assert token == TOKEN_DATA


def test_refresh_token(respx_mock):
    respx_mock.post(
        TOKEN_URL,
        data={
            "client_id": "client-id",
            "client_secret": "S3cr3t!",
            "grant_type": "refresh_token",
            "refresh_token": "refresh-token",
        },
    ).respond(200, json=RDV_SERVICE_PUBLIC_TOKEN_BODY)
    assert rdv_service_public.get_oauth_client().refresh_token("refresh-token") == TOKEN_DATA


def test_token_invalid_grant(respx_mock):
    respx_mock.post(TOKEN_URL).respond(400, json={"error": "invalid_grant", "error_description": "..."})
    client = rdv_service_public.get_oauth_client()

    with pytest.raises(rdv_service_public.RdvServicePublicInvalidTokenError):
        client.get_token(code="expired-code", redirect_uri=REDIRECT_URI)
    with pytest.raises(rdv_service_public.RdvServicePublicInvalidTokenError):
        client.refresh_token("revoked-refresh-token")


def test_token_errors(respx_mock):
    client = rdv_service_public.get_oauth_client()

    respx_mock.post(TOKEN_URL).mock(side_effect=httpx.ReadTimeout)
    with pytest.raises(rdv_service_public.RdvServicePublicApiError, match="ReadTimeout"):
        client.refresh_token("refresh-token")

    # Wrong credentials of the Les Emplois application: linking the account again would not help
    respx_mock.post(TOKEN_URL).respond(401, json={"error": "invalid_client"})
    with pytest.raises(rdv_service_public.RdvServicePublicRequestRefusedError, match="code=401"):
        client.refresh_token("refresh-token")

    respx_mock.post(TOKEN_URL).respond(400, content="not json")
    with pytest.raises(rdv_service_public.RdvServicePublicApiError, match="JSONDecodeError"):
        client.refresh_token("refresh-token")


def test_get_me(respx_mock):
    respx_mock.get(ME_URL, headers={"Authorization": "Bearer access-token"}).respond(
        200, json=RDV_SERVICE_PUBLIC_AGENT_BODY
    )
    assert rdv_service_public.get_api_client("access-token").get_me() == rdv_service_public.Agent(
        id=42, email="alice.martin@example.com"
    )


def test_create_rdv_plan(respx_mock):
    user = {"first_name": "Jacques", "last_name": "Henry", "email": "jacques.henry@example.com"}
    respx_mock.post(
        RDV_PLANS_URL,
        headers={"Authorization": "Bearer access-token"},
        json={
            "user": user,
            "return_url": "https://emplois.fake/return",
            "dossier_url": "https://emplois.fake/dossier",
        },
    ).respond(201, json=RDV_SERVICE_PUBLIC_RDV_PLAN_BODY)

    rdv_plan = rdv_service_public.get_api_client("access-token").create_rdv_plan(
        user=user, return_url="https://emplois.fake/return", dossier_url="https://emplois.fake/dossier"
    )
    assert rdv_plan == rdv_service_public.RdvPlan(
        id=1234, user_id=5678, url="https://rdv-service-public.fake/agents/rdv_plans/1234"
    )


def test_create_rdv_plan_invalid_user(respx_mock):
    respx_mock.post(RDV_PLANS_URL).respond(
        422,
        json={
            "errors": {"phone_number": [{"error": "invalid"}]},
            "error_messages": ["phone_number n'est pas valide"],
        },
    )

    with pytest.raises(rdv_service_public.RdvServicePublicRequestRefusedError) as exc_info:
        rdv_service_public.get_api_client("access-token").create_rdv_plan(
            user={}, return_url="https://emplois.fake/return", dossier_url="https://emplois.fake/dossier"
        )
    assert exc_info.value.invalid_fields == {"phone_number"}
    assert str(exc_info.value) == "RdvServicePublicRequestRefusedError(code=422, invalid_fields=['phone_number'])"


def test_api_invalid_token(respx_mock):
    respx_mock.get(ME_URL).respond(401)
    with pytest.raises(rdv_service_public.RdvServicePublicInvalidTokenError):
        rdv_service_public.get_api_client("access-token").get_me()


def test_api_errors(respx_mock):
    client = rdv_service_public.get_api_client("access-token")

    respx_mock.get(ME_URL).mock(side_effect=httpx.ReadTimeout)
    with pytest.raises(rdv_service_public.RdvServicePublicApiError, match="ReadTimeout"):
        client.get_me()

    # Refused by the permissions of RDV Service Public: the access token is valid
    respx_mock.get(ME_URL).respond(403, json={"errors": [{"base": "forbidden"}]})
    with pytest.raises(rdv_service_public.RdvServicePublicRequestRefusedError, match="code=403"):
        client.get_me()

    # Unlike a refusal, sending the request again later may work
    respx_mock.get(ME_URL).respond(500)
    with pytest.raises(rdv_service_public.RdvServicePublicApiError, match="HTTPStatusError") as exc_info:
        client.get_me()
    assert type(exc_info.value) is rdv_service_public.RdvServicePublicApiError

    respx_mock.get(ME_URL).respond(200, content="not json")
    with pytest.raises(rdv_service_public.RdvServicePublicApiError, match="JSONDecodeError"):
        client.get_me()
