import os
from urllib.parse import urljoin

import httpx
import respx
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from itou.rdv_insertion.api import RDV_S_CREDENTIALS_CACHE_KEY, get_api_credentials
from itou.utils.mocks.rdv_insertion import (
    RDV_INSERTION_AUTH_FAILURE_BODY,
    RDV_INSERTION_AUTH_SUCCESS_BODY,
    RDV_INSERTION_AUTH_SUCCESS_HEADERS,
)
from tests.utils.test import TestCase


@override_settings(
    RDV_SOLIDARITES_API_BASE_URL="https://rdv-solidarites.fake/api/v1/",
    RDV_SOLIDARITES_EMAIL="tech@inclusion.beta.gouv.fr",
    RDV_SOLIDARITES_PASSWORD="password",
    RDV_SOLIDARITES_TOKEN_EXPIRY=86000,
    CACHES={
        "default": {
            "BACKEND": "itou.utils.cache.UnclearableCache",
            "LOCATION": f"{os.environ['REDIS_URL']}?db={os.environ['REDIS_DB']}",
            "KEY_PREFIX": "test_rdv_insertion",
        }
    },
)
class RDVInsertionTokenRenewalTest(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        respx.post(
            urljoin(settings.RDV_SOLIDARITES_API_BASE_URL, "/auth/sign_in"), name="rdv_solidarites_sign_in"
        ).mock(
            return_value=httpx.Response(
                200, json=RDV_INSERTION_AUTH_SUCCESS_BODY, headers=RDV_INSERTION_AUTH_SUCCESS_HEADERS
            )
        )

    @respx.mock
    def test_renewal_success(self):
        credentials = get_api_credentials()
        assert credentials == RDV_INSERTION_AUTH_SUCCESS_HEADERS
        assert respx.routes["rdv_solidarites_sign_in"].called

    @respx.mock
    def test_renewal_success_cache(self):
        credentials = get_api_credentials()
        assert credentials == RDV_INSERTION_AUTH_SUCCESS_HEADERS
        assert respx.routes["rdv_solidarites_sign_in"].call_count == 1

        # Subsequent calls should hit the cache
        credentials = get_api_credentials()
        assert credentials == RDV_INSERTION_AUTH_SUCCESS_HEADERS
        assert respx.routes["rdv_solidarites_sign_in"].call_count == 1

    @respx.mock
    def test_renewal_success_ignore_cache(self):
        credentials = get_api_credentials()
        assert credentials == RDV_INSERTION_AUTH_SUCCESS_HEADERS
        assert respx.routes["rdv_solidarites_sign_in"].call_count == 1

        # Should not hit the cache with refresh=True
        credentials = get_api_credentials(refresh=True)
        assert credentials == RDV_INSERTION_AUTH_SUCCESS_HEADERS
        assert respx.routes["rdv_solidarites_sign_in"].call_count == 2

    @respx.mock
    def test_renewal_failure_rdvi_error(self):
        respx.routes["rdv_solidarites_sign_in"].mock(
            return_value=httpx.Response(401, json=RDV_INSERTION_AUTH_FAILURE_BODY)
        )
        with self.assertRaises(httpx.HTTPStatusError):
            get_api_credentials()
        assert respx.routes["rdv_solidarites_sign_in"].call_count == 1
        assert cache.ttl(RDV_S_CREDENTIALS_CACHE_KEY) == 0  # Cache key not found (0: not found / None: no expiry)

        # Subsequent calls should not hit the cache for failed attempts
        with self.assertRaises(httpx.HTTPStatusError):
            get_api_credentials()
        assert respx.routes["rdv_solidarites_sign_in"].call_count == 2
        assert cache.ttl(RDV_S_CREDENTIALS_CACHE_KEY) == 0

    @respx.mock
    @override_settings(RDV_SOLIDARITES_API_BASE_URL=None)
    def test_renewal_failure_rdvi_misconfiguration(self):
        with self.assertRaises(ImproperlyConfigured):
            get_api_credentials()
        assert not respx.routes["rdv_solidarites_sign_in"].called
        assert cache.ttl(RDV_S_CREDENTIALS_CACHE_KEY) == 0
