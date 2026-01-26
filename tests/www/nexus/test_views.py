from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from itoutils.urls import add_url_params
from pytest_django.asserts import assertRedirects

from tests.users.factories import PrescriberFactory


class TestAutoLogin:
    def test_login_required(self, client):
        next_url = f"https://{settings.NEXUS_ALLOWED_REDIRECT_HOSTS[0]}"
        url = reverse("nexus:auto_login", query={"next_url": next_url})
        response = client.get(url)
        assertRedirects(response, add_url_params(reverse("account_login"), {"next": url}))

    def test_nominal_case(self, client, mock_nexus_token):
        client.force_login(PrescriberFactory())
        for host in settings.NEXUS_ALLOWED_REDIRECT_HOSTS:
            next_url = f"https://{host}"
            url = reverse("nexus:auto_login", query={"next_url": next_url})
            response = client.get(url)
            assertRedirects(response, add_url_params(next_url, {"auto_login": "JWT"}), fetch_redirect_response=False)

    def test_missing_next_url(self, client):
        client.force_login(PrescriberFactory())
        # Without next_url
        url = reverse("nexus:auto_login")
        response = client.get(url)
        assert response.status_code == 404

    def test_bad_host(self, client):
        client.force_login(PrescriberFactory())
        next_url = "https://empl0is.fr"
        url = reverse("nexus:auto_login", query={"next_url": next_url})
        response = client.get(url)
        assert response.status_code == 404

    @override_settings(PDI_JWT_KEY=None)
    def test_no_settings(self, client):
        client.force_login(PrescriberFactory())
        next_url = f"https://{settings.NEXUS_ALLOWED_REDIRECT_HOSTS[0]}"
        url = reverse("nexus:auto_login", query={"next_url": next_url})
        response = client.get(url)
        assert response.status_code == 404
