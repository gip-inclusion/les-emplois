import pytest
from django.test import TestCase
from django.test.client import Client


class HtmxClient(Client):
    def generic(self, method, path, data="", content_type="application/octet-stream", secure=False, **extra):
        # Add HTMX-specific headers according to your needs.
        # https://htmx.org/reference/#request_headers
        htmx_headers = {
            "HTTP_HX_REQUEST": "true",
        }
        extra = htmx_headers | extra
        return super().generic(method=method, path=path, data=data, content_type=content_type, secure=secure, **extra)


# Compatibility with Unittest
class HtmxTestCase(TestCase):
    """
    Mimic a response to an HTMX request.

    Usage
    ```
    class MyTestWithUnittest(itou.utils.htmx.testing.HtmxTestCase):
        def a_test(self):
            response = self.htmx_client.get("/)
    ```
    """

    @pytest.fixture(autouse=True)
    def htmx_client(self):
        self.htmx_client = HtmxClient()
