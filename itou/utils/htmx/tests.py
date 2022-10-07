from django_htmx.middleware import HtmxDetails

from .testing import HtmxTestCase


# Unittest style
class HtmxRequestFactoryTest(HtmxTestCase):
    def test_get(self):
        response = self.htmx_client.get("/")
        assert response.status_code == 200
        assert isinstance(response.wsgi_request.htmx, HtmxDetails)
        assert response.wsgi_request.htmx.boosted is False

    def test_post(self):
        response = self.htmx_client.post("/")
        assert response.status_code == 200
        assert isinstance(response.wsgi_request.htmx, HtmxDetails)
        assert response.wsgi_request.htmx.boosted is False


# Pytest style
def test_htmx_client(htmx_client):
    response = htmx_client.get("/")
    assert response.status_code == 200
    assert isinstance(response.wsgi_request.htmx, HtmxDetails)
    assert response.wsgi_request.htmx.boosted is False
