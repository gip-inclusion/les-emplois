from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from itou.utils.new_dns.middleware import NewDnsRedirectMiddleware


class NewDnsRedirectMiddlewareTest(SimpleTestCase):
    def setUp(self):
        self.request_factory = RequestFactory()
        self.middleware = NewDnsRedirectMiddleware(HttpResponse)

    @override_settings(ALLOWED_HOSTS=["inclusion.beta.gouv.fr", "emplois.inclusion.beta.gouv.fr"])
    def test_inclusion_redirect(self):
        path = "/accounts/login/?account_type=job_seeker"
        request = self.request_factory.get(path, HTTP_HOST="inclusion.beta.gouv.fr")

        response = self.middleware(request)

        assert response.status_code == 301
        assert response["Location"] == f"https://emplois.inclusion.beta.gouv.fr{path}"

    @override_settings(ALLOWED_HOSTS=["emploi.inclusion.beta.gouv.fr", "emplois.inclusion.beta.gouv.fr"])
    def test_emploi_redirect(self):
        path = "/accounts/login/?account_type=job_seeker"
        request = self.request_factory.get(path, HTTP_HOST="emploi.inclusion.beta.gouv.fr")

        response = self.middleware(request)

        assert response.status_code == 301
        assert response["Location"] == f"https://emplois.inclusion.beta.gouv.fr{path}"

    @override_settings(ALLOWED_HOSTS=["demo.inclusion.beta.gouv.fr", "demo.emplois.inclusion.beta.gouv.fr"])
    def test_demo_redirect(self):
        path = "/accounts/login/?account_type=job_seeker"
        request = self.request_factory.get(path, HTTP_HOST="demo.inclusion.beta.gouv.fr")

        response = self.middleware(request)

        assert response.status_code == 301
        assert response["Location"] == f"https://demo.emplois.inclusion.beta.gouv.fr{path}"

    @override_settings(ALLOWED_HOSTS=["localhost"])
    def test_non_redirect(self):
        request = self.request_factory.get("/", HTTP_HOST="localhost", SERVER_PORT="8080")

        response = self.middleware(request)

        assert response.status_code == 200
