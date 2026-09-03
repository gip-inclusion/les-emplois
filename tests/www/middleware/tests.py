from django.conf import settings
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

        user = PrescriberFactory(membership=True)
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


def test_browser_id_cookie_not_set_for_viewers(client):
    """Browser id cookies are used to track browser doing sensitive operations.
    Someone that just browse the website is not concerned."""
    response = client.get("/")
    assert not response.cookies


def test_browser_id_cookie_for_authenticated_users(client):
    """At first POST, everyone gets a browser id cookie uniquely identifying its browser."""
    response = client.post("/")
    assert response.cookies[settings.BROWSER_ID_COOKIE_NAME]


def test_browser_id_cookie_is_stable_between_requests(client):
    """The browser id cookie tracks a browser:
    it should not change from an HTTP query to another."""
    cookies = set()

    for _ in range(3):
        response = client.post("/")
        cookies.add(response.cookies[settings.BROWSER_ID_COOKIE_NAME].value)

    assert len(cookies) == 1


def test_browser_id_cookie_differ_for_different_browsers(client):
    """The browser id cookie uniquely tracks a browser, this test simulates a second
    browser, which gets a different browser_id cookie."""
    cookies = set()

    response = client.post("/")
    cookies.add(response.cookies[settings.BROWSER_ID_COOKIE_NAME].value)

    del client.cookies[settings.BROWSER_ID_COOKIE_NAME]

    response = client.post("/")
    cookies.add(response.cookies[settings.BROWSER_ID_COOKIE_NAME].value)

    assert len(cookies) == 2


def test_browser_id_cookie_is_kept_between_user_sessions(client):
    """The browser id cookie tracks a browser, not a user."""
    user_a = ItouStaffFactory()
    user_b = ItouStaffFactory()
    cookies = set()

    client.force_login(user_a)
    response = client.post("/")
    cookies.add(response.cookies[settings.BROWSER_ID_COOKIE_NAME].value)

    client.force_login(user_b)
    response = client.post("/")
    cookies.add(response.cookies[settings.BROWSER_ID_COOKIE_NAME].value)

    assert len(cookies) == 1
