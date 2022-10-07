"""
Utilities useful when testing HTMX-related features.
"""

from typing import cast

from django.core.handlers.wsgi import WSGIRequest
from django.test import RequestFactory as BaseRequestFactory
from django.test.client import MULTIPART_CONTENT
from django_htmx.middleware import HtmxDetails


class HtmxWSGIRequest(WSGIRequest):
    htmx: HtmxDetails


class HtmxRequestFactory(BaseRequestFactory):
    def _default_headers(self, boosted=False):
        # NOTE(celinems): this list is to be completed according to our needs.
        # https://htmx.org/reference/#request_headers
        return {
            "HTTP_HX_REQUEST": "true",
            "HTTP_HX_BOOSTED": str(boosted).lower(),
        }

    def get(self, path, data=None, secure=False, boosted=False) -> HtmxWSGIRequest:
        extra_htmx_headers = self._default_headers(boosted=boosted)
        return cast(HtmxWSGIRequest, super().get(path, data, secure, **extra_htmx_headers))

    def post(self, path, data=None, content_type=MULTIPART_CONTENT, secure=False, boosted=False):
        extra_htmx_headers = self._default_headers(boosted=boosted)
        return cast(HtmxWSGIRequest, super().post(path, data, content_type, secure, **extra_htmx_headers))
