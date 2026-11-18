import datetime

import pytest
from django.utils import timezone
from freezegun import freeze_time

from itou.rdv_service_public.models import OAuthToken
from itou.utils.apis.rdv_service_public import RdvServicePublicApiError, RdvServicePublicInvalidTokenError
from itou.utils.mocks.rdv_service_public import RDV_SERVICE_PUBLIC_TOKEN_BODY
from tests.rdv_service_public.factories import OAuthTokenFactory


TOKEN_URL = "https://rdv-service-public.fake/oauth/token"


@pytest.fixture(autouse=True)
def rdvsp_settings(settings):
    settings.RDV_SERVICE_PUBLIC_BASE_URL = "https://rdv-service-public.fake"
    settings.RDV_SERVICE_PUBLIC_CLIENT_ID = "client-id"
    settings.RDV_SERVICE_PUBLIC_CLIENT_SECRET = "S3cr3t!"
    return settings


class TestRefreshAccessToken:
    @freeze_time("2026-11-18 10:00")
    def test_refresh(self, respx_mock):
        token = OAuthTokenFactory(
            refresh_token="old-refresh-token",
            expires_at=timezone.now() + datetime.timedelta(seconds=30),
        )
        respx_mock.post(
            TOKEN_URL,
            data={
                "client_id": "client-id",
                "client_secret": "S3cr3t!",
                "grant_type": "refresh_token",
                "refresh_token": "old-refresh-token",
            },
        ).respond(200, json=RDV_SERVICE_PUBLIC_TOKEN_BODY)

        token.refresh_access_token()
        assert token.access_token == "access-token"
        token.refresh_from_db()
        assert token.access_token == "access-token"
        assert token.refresh_token == "refresh-token"
        assert token.expires_at == datetime.datetime(2026, 11, 18, 12, 0, tzinfo=datetime.UTC)

    def test_already_refreshed(self, respx_mock):
        token = OAuthTokenFactory(expires_at=timezone.now())
        # A concurrent request refreshed the token in the meantime
        OAuthToken.objects.filter(pk=token.pk).update(
            access_token="new-access-token", expires_at=timezone.now() + datetime.timedelta(minutes=2)
        )

        # No route: any request to RDV Service Public would fail the test
        token.refresh_access_token()
        assert token.access_token == "new-access-token"

    def test_refused(self, respx_mock):
        token = OAuthTokenFactory(expires_at=timezone.now())
        respx_mock.post(TOKEN_URL).respond(400, json={"error": "invalid_grant"})

        with pytest.raises(RdvServicePublicInvalidTokenError):
            token.refresh_access_token()

    def test_deleted_by_a_concurrent_request(self, respx_mock):
        token = OAuthTokenFactory(expires_at=timezone.now())
        OAuthToken.objects.filter(pk=token.pk).delete()

        with pytest.raises(RdvServicePublicInvalidTokenError):
            token.refresh_access_token()

    def test_rdv_service_public_unavailable(self, respx_mock):
        token = OAuthTokenFactory(refresh_token="refresh-token", expires_at=timezone.now())
        respx_mock.post(TOKEN_URL).respond(500)

        with pytest.raises(RdvServicePublicApiError):
            token.refresh_access_token()
        # The token is kept, to be refreshed once RDV Service Public is back
        token.refresh_from_db()
        assert token.refresh_token == "refresh-token"
