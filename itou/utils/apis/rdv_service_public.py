"""RDV Service Public API, called on behalf of each employer with their own OAuth token."""

import dataclasses
import json

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.http import urlencode


API_TIMEOUT_SECONDS = 5.0
OAUTH_SCOPE = "write"


class RdvServicePublicApiError(Exception):
    pass


class RdvServicePublicInvalidTokenError(RdvServicePublicApiError):
    """The OAuth code or token was refused: the user must link their RDV Service Public account again."""


class RdvServicePublicRequestRefusedError(RdvServicePublicApiError):
    """RDV Service Public refused the request (4xx response): sending it again would not help."""

    def __init__(self, response_code, response_data):
        self.response_code = response_code
        self.response_data = response_data
        super().__init__()

    def __str__(self):
        # Without the response data: it can contain personal data, like a refused value
        return f"{self.__class__.__name__}(code={self.response_code}, invalid_fields={sorted(self.invalid_fields)})"

    @property
    def invalid_fields(self):
        """The fields refused by a validation error: {"errors": {"phone_number": [{"error": "invalid"}]}}."""
        errors = self.response_data.get("errors") if isinstance(self.response_data, dict) else None
        return set(errors) if isinstance(errors, dict) else set()


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class TokenData:
    access_token: str
    refresh_token: str
    expires_in: int  # seconds


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class Agent:
    id: int
    email: str


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class RdvPlan:
    id: int
    user_id: int
    url: str


class RdvServicePublicOAuthClient:
    """Calls made with the credentials of the Les Emplois OAuth application."""

    def __init__(self, base_url: str, client_id: str, client_secret: str):
        self.base_url = base_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.client = httpx.Client(base_url=base_url, timeout=API_TIMEOUT_SECONDS)

    def get_authorize_url(self, *, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": OAUTH_SCOPE,
            "state": state,
        }
        return f"{self.base_url}/oauth/authorize?{urlencode(params)}"

    def get_token(self, *, code: str, redirect_uri: str) -> TokenData:
        # The OAuth standard requires the redirect_uri of the authorization request, RDV Service Public checks it
        return self._request_token(grant_type="authorization_code", code=code, redirect_uri=redirect_uri)

    def refresh_token(self, refresh_token: str) -> TokenData:
        return self._request_token(grant_type="refresh_token", refresh_token=refresh_token)

    def _request_token(self, **data) -> TokenData:
        try:
            response = self.client.post(
                "oauth/token",
                data={"client_id": self.client_id, "client_secret": self.client_secret, **data},
            )
            # The code or the refresh token is expired, revoked or already used
            if response.status_code == httpx.codes.BAD_REQUEST and response.json().get("error") == "invalid_grant":
                raise RdvServicePublicInvalidTokenError("RDV Service Public refused the OAuth grant")
            if response.is_client_error:
                raise RdvServicePublicRequestRefusedError(response.status_code, response.json())
            body = response.raise_for_status().json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise RdvServicePublicApiError(
                f"Error requesting RDV Service Public token: {exc.__class__.__name__}"
            ) from exc
        return TokenData(
            access_token=body["access_token"], refresh_token=body["refresh_token"], expires_in=body["expires_in"]
        )


class RdvServicePublicApiClient:
    """Calls made on behalf of an agent, with their access token."""

    def __init__(self, base_url: str, access_token: str):
        self.client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=API_TIMEOUT_SECONDS,
        )

    def get_me(self) -> Agent:
        """The agent owning the access token."""
        agent = self._request("GET", "api/v1/agents/me")["agent"]
        return Agent(id=agent["id"], email=agent["email"])

    def create_rdv_plan(self, *, user: dict, return_url: str, dossier_url: str) -> RdvPlan:
        """Create a rdv_plan for this job seeker: the agent then books the appointment by following its url.

        return_url: target of the "Retour sur Les Emplois" button, while booking in RDV Service Public.
        dossier_url: target of the "Voir sur Les Emplois" button, on the appointment page in RDV Service Public.
        """
        rdv_plan = self._request(
            "POST",
            "api/v1/rdv_plans",
            json={"user": user, "return_url": return_url, "dossier_url": dossier_url},
        )["rdv_plan"]
        return RdvPlan(id=rdv_plan["id"], user_id=rdv_plan["user_id"], url=rdv_plan["url"])

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self.client.request(method, path, **kwargs)
            if response.status_code == httpx.codes.UNAUTHORIZED:
                raise RdvServicePublicInvalidTokenError("RDV Service Public refused the access token")
            if response.is_client_error:
                raise RdvServicePublicRequestRefusedError(response.status_code, response.json())
            return response.raise_for_status().json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise RdvServicePublicApiError(
                f"Error requesting RDV Service Public API: {exc.__class__.__name__}"
            ) from exc


def _check_configuration():
    if not (
        settings.RDV_SERVICE_PUBLIC_BASE_URL
        and settings.RDV_SERVICE_PUBLIC_CLIENT_ID
        and settings.RDV_SERVICE_PUBLIC_CLIENT_SECRET
    ):
        raise ImproperlyConfigured("Missing configuration for RDV Service Public API")


def get_oauth_client():
    _check_configuration()
    return RdvServicePublicOAuthClient(
        base_url=settings.RDV_SERVICE_PUBLIC_BASE_URL,
        client_id=settings.RDV_SERVICE_PUBLIC_CLIENT_ID,
        client_secret=settings.RDV_SERVICE_PUBLIC_CLIENT_SECRET,
    )


def get_api_client(access_token: str):
    _check_configuration()
    return RdvServicePublicApiClient(base_url=settings.RDV_SERVICE_PUBLIC_BASE_URL, access_token=access_token)
