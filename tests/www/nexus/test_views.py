from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from itoutils.urls import add_url_params
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.nexus.enums import Auth, NexusUserKind, Service
from itou.nexus.models import NexusUser
from tests.nexus.factories import NexusUserFactory
from tests.users.factories import PrescriberFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented


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

    @override_settings(NEXUS_AUTO_LOGIN_KEY=None)
    def test_no_settings(self, client):
        client.force_login(PrescriberFactory())
        next_url = f"https://{settings.NEXUS_ALLOWED_REDIRECT_HOSTS[0]}"
        url = reverse("nexus:auto_login", query={"next_url": next_url})
        response = client.get(url)
        assert response.status_code == 404


class TestLayout:
    def test_footer(self, client, snapshot):
        user = PrescriberFactory(for_snapshot=True)
        NexusUserFactory(
            email=user.email, kind=NexusUserKind.FACILITY_MANAGER, source=Service.EMPLOIS, auth=Auth.PRO_CONNECT
        )
        client.force_login(user)
        response = client.get(reverse("nexus:homepage"))

        soup = parse_response_to_soup(response, "#footer")
        for a_tags in soup.find_all("a", attrs={"href": True}):
            if a_tags["href"].startswith("/static/pdf/syntheseSecurite"):
                a_tags["href"] = "/static/pdf/syntheseSecurite.pdf"  # Normalize href for CI
        assert pretty_indented(parse_response_to_soup(response, "#footer")) == snapshot

    def test_header_titles(self, client, snapshot):
        user = PrescriberFactory(for_snapshot=True)
        client.force_login(user)

        # If there's only FACILITY_MANAGER kinds
        NexusUserFactory(
            email=user.email, kind=NexusUserKind.FACILITY_MANAGER, source=Service.EMPLOIS, auth=Auth.PRO_CONNECT
        )
        response = client.get(reverse("nexus:homepage"))
        assert pretty_indented(parse_response_to_soup(response, "#header")) == snapshot(name="facility_manager")

        # if there are both kinds -> also use FACILITY_MANAGER title
        NexusUserFactory(email=user.email, kind=NexusUserKind.GUIDE, source=Service.DORA, auth=Auth.PRO_CONNECT)
        response = client.get(reverse("nexus:homepage"))
        assert pretty_indented(parse_response_to_soup(response, "#header")) == snapshot(name="facility_manager")

        # Only use GUIDE layout if there are only GUIDE kinds
        NexusUser.objects.filter(kind=NexusUserKind.FACILITY_MANAGER).delete()
        response = client.get(reverse("nexus:homepage"))
        assert pretty_indented(parse_response_to_soup(response, "#header")) == snapshot(name="guide")

    def test_header_activated_badge(self, client, snapshot):
        user = PrescriberFactory(for_snapshot=True)
        NexusUserFactory(
            email=user.email, kind=NexusUserKind.FACILITY_MANAGER, source=Service.PILOTAGE, auth=Auth.PRO_CONNECT
        )
        client.force_login(user)

        response = client.get(reverse("nexus:homepage"))
        assert pretty_indented(parse_response_to_soup(response, "#header")) == snapshot(name="no_badge")

        NexusUserFactory(email=user.email, source=Service.EMPLOIS)
        NexusUserFactory(email=user.email, source=Service.DORA)
        response = client.get(reverse("nexus:homepage"))
        assert pretty_indented(parse_response_to_soup(response, "#header")) == snapshot(name="all_badges")


class TestHomePageView:
    url = reverse("nexus:homepage")
    ACTIVATE_SERVICES_H2 = "Mes services actifs"
    NEW_SERVICES_H2 = "Services à découvrir"

    def test_one_activated_service(self, client, snapshot):
        user = PrescriberFactory()
        nexus_user = NexusUserFactory(
            email=user.email, source=Service.EMPLOIS, auth=Auth.PRO_CONNECT, kind=NexusUserKind.FACILITY_MANAGER
        )
        client.force_login(user)

        response = client.get(self.url)

        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot(name="facility_manager")
        assertContains(response, self.ACTIVATE_SERVICES_H2)
        assertContains(response, self.NEW_SERVICES_H2)

        nexus_user.kind = NexusUserKind.GUIDE
        nexus_user.save()
        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot(name="guide")

    def test_all_activated_services(self, client, snapshot):
        user = PrescriberFactory()
        for service in Service.activable():
            NexusUserFactory(email=user.email, source=service, auth=Auth.PRO_CONNECT)
        client.force_login(user)

        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot
        assertContains(response, self.ACTIVATE_SERVICES_H2)
        assertNotContains(response, self.NEW_SERVICES_H2)

    def test_missing_emplois_log(self, client, caplog):
        # This should not happen for now since there's a les-emplois User -> les-empois should be activated
        # Still, the code allows it, and it might become possible someday
        user = PrescriberFactory()
        NexusUserFactory(email=user.email, source=Service.DORA, auth=Auth.PRO_CONNECT)
        client.force_login(user)

        client.get(self.url)
        assert caplog.messages == [f"User is missing it's NexusUser user={user.pk}", "HTTP 200 OK"]
