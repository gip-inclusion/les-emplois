import pytest
from django.urls import reverse
from itoutils.urls import add_url_params
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from tests.users.factories import PrescriberFactory, random_user_kind_factory


def test_home_anonymous(client, settings):
    settings.PLATEFORME_ACCUEIL_BASE_URL = "https://plateforme.accueil.fr"
    url = reverse("home:hp")
    response = client.get(url, follow=True)
    assertRedirects(response, reverse("search:home"))
    assertContains(
        response,
        'data-plateforme-accueil="https://plateforme.accueil.fr?host=localhost%3A8000"',
    )


def test_home_logged_in(client):
    client.force_login(PrescriberFactory())
    url = reverse("home:hp")
    response = client.get(url, follow=True)
    assertRedirects(response, reverse("dashboard:index"))
    assertContains(response, "Rechercher un emploi inclusif")


class TestHomeRedirect:
    banner = "La plateforme de l’inclusion change d’adresse."
    notice = "Vous arrivez de l’ancienne adresse"

    @pytest.fixture(autouse=True)
    def home_redirect_settings(self, settings):
        settings.NEW_DOMAIN = "new.domain"
        settings.ALLOWED_HOSTS = ["old.domain", settings.NEW_DOMAIN]
        settings.REDIRECT_TO_NEW_DOMAIN = True

    def test_redirected_from_old_domain_with_notice(self, client):
        home_url = reverse("search:home")

        response = client.get(home_url, HTTP_HOST="old.domain")
        assertRedirects(
            response,
            f"https://new.domain{home_url}?redirected-from-old-domain=1",
            fetch_redirect_response=False,
        )

        response = client.get(home_url, HTTP_HOST="new.domain", data={"redirected-from-old-domain": "1"})
        assertRedirects(response, home_url, fetch_redirect_response=False)
        response = client.get(response.url, HTTP_HOST="new.domain")
        assertContains(response, '<iframe id="plateforme-accueil-iframe"')  # the home page
        assertContains(response, self.banner)
        assert "redirected-from-old-domain" in client.session

        user = random_user_kind_factory(identity_provider="DJANGO")
        login_url = reverse("account_login")
        response = client.post(login_url, HTTP_HOST="new.domain", data={"email": user.email})
        assertRedirects(
            response,
            add_url_params(reverse("login:existing_user"), {"back_url": login_url}),
            fetch_redirect_response=False,
        )
        response = client.get(response.url, HTTP_HOST="new.domain")
        assertContains(response, self.notice)

    def test_new_domain_no_notice(self, client):
        response = client.get(reverse("search:home"), HTTP_HOST="new.domain")
        assertContains(response, '<iframe id="plateforme-accueil-iframe"')  # the home page
        assertNotContains(response, self.banner)
        user = random_user_kind_factory(identity_provider="DJANGO")
        response = client.post(
            reverse("account_login"),
            HTTP_HOST="new.domain",
            data={"email": user.email},
            follow=True,
        )
        assertNotContains(response, self.notice)
