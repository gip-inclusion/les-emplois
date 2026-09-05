from django.urls import reverse

from tests.companies.factories import CompanyFactory
from tests.otp.factories import ItouTOTPDeviceFactory
from tests.users.factories import ItouStaffFactory, PrescriberFactory


class TestRedirectToNewDomainMiddleware:
    def test_redirect_staff(self, settings, client):
        settings.NEW_DOMAIN = "new.domain"
        settings.ALLOWED_HOSTS = ["old.domain", settings.NEW_DOMAIN]

        user = ItouStaffFactory()
        client.force_login(user)
        response = client.get("/admin/", HTTP_HOST="old.domain")
        assert response.status_code == 200  # no redirect (not enabled)

        settings.REDIRECT_TO_NEW_DOMAIN = True
        response = client.get(
            "/admin/",
            query_params={"foo": "bar"},
            HTTP_HOST="old.domain",
            follow=False,
        )
        assert response.status_code == 302
        assert response.url == "https://new.domain/admin/?foo=bar&redirected-from-old-domain=1"

        response = client.get("/admin/", HTTP_HOST="new.domain")
        assert response.status_code == 200  # no redirect (already on new domain)

    def test_do_not_redirect_non_staff(self, settings, client):
        settings.NEW_DOMAIN = "new.domain"
        settings.ALLOWED_HOSTS = ["old.domain", settings.NEW_DOMAIN]
        settings.REDIRECT_TO_NEW_DOMAIN = True

        response = client.get("/search/employers", HTTP_HOST="old.domain", follow=False)
        assert response.status_code == 200

        user = PrescriberFactory()
        client.force_login(user)
        response = client.get("/dashboard/", HTTP_HOST="old.domain", follow=False)
        assert response.status_code == 200

    def test_do_not_redirect_api_clients(self, settings, api_client):
        settings.NEW_DOMAIN = "new.domain"
        settings.ALLOWED_HOSTS = ["old.domain", settings.NEW_DOMAIN]
        settings.REDIRECT_TO_NEW_DOMAIN = True

        user = CompanyFactory(with_membership=True).members.first()
        api_client.force_authenticate(user)
        response = api_client.get(reverse("v1:applicants-list"), HTTP_HOST="old.domain")
        assert response.status_code == 200  # no redirect

    def test_do_not_redirect_otp_verify_form(self, settings, client):
        settings.NEW_DOMAIN = "new.domain"
        settings.ALLOWED_HOSTS = ["old.domain", settings.NEW_DOMAIN]
        settings.REDIRECT_TO_NEW_DOMAIN = True
        settings.REQUIRE_OTP_FOR_STAFF = True

        user = ItouStaffFactory()
        ItouTOTPDeviceFactory(user=user)
        client.force_login(user)
        response = client.get(
            "/otp/verify",
            query_params={"next": "/some/restricted/page"},
            HTTP_HOST="old.domain",
            follow=False,
        )
        assert response.status_code == 200  # no rediect
