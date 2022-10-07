from django.http import HttpResponse
from django.test import SimpleTestCase
from django_htmx.middleware import HtmxMiddleware

from .utilities_for_testing import HtmxRequestFactory


class HtmxRequestFactoryTest(SimpleTestCase):
    def setUp(self):
        self.htmx_request = HtmxRequestFactory()
        self.middleware = HtmxMiddleware(HttpResponse)

    def test_get(self):
        request = self.htmx_request.get("/")
        response = self.middleware(request)
        assert response.status_code == 200
        assert bool(request.htmx) is True
        assert request.htmx.boosted is False

        # Boosted request
        request = self.htmx_request.get("/", boosted=True)
        response = self.middleware(request)
        assert response.status_code == 200
        assert request.htmx.boosted is True

    def test_post(self):
        request = self.htmx_request.post("/")
        response = self.middleware(request)
        assert response.status_code == 200
        assert bool(request.htmx) is True
        assert request.htmx.boosted is False

        # Boosted request
        request = self.htmx_request.post("/", boosted=True)
        response = self.middleware(request)
        assert response.status_code == 200
        assert request.htmx.boosted is True
