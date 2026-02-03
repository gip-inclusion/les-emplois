import datetime

from django.conf import settings
from django.contrib import messages
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from itoutils.urls import add_url_params
from pytest_django.asserts import (
    assertContains,
    assertMessages,
    assertNotContains,
    assertQuerySetEqual,
    assertRedirects,
)

from itou.nexus.enums import Auth, NexusUserKind, Service
from itou.nexus.models import ActivatedService, NexusUser
from itou.users.enums import UserKind
from tests.companies.factories import CompanyMembershipFactory, JobDescriptionFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.nexus.factories import NexusUserFactory
from tests.users.factories import EmployerFactory, PrescriberFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented, remove_static_hash


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


class TestLayout:
    def test_footer(self, client, snapshot):
        user = PrescriberFactory(for_snapshot=True)
        client.force_login(user)
        response = client.get(reverse("nexus:homepage"))

        soup = parse_response_to_soup(response, "#footer")
        for a_tags in soup.find_all("a", attrs={"href": True}):
            if a_tags["href"].startswith("/static/pdf/syntheseSecurite"):
                a_tags["href"] = remove_static_hash(a_tags["href"])  # Normalize href for CI
        assert pretty_indented(soup) == snapshot

    def test_header_titles(self, client, snapshot):
        user = EmployerFactory(for_snapshot=True, membership=True)
        client.force_login(user)

        # If there's only FACILITY_MANAGER kinds
        response = client.get(reverse("nexus:homepage"))
        assert pretty_indented(parse_response_to_soup(response, "#header")) == snapshot(name="facility_manager")

        # If there are both kinds -> also use FACILITY_MANAGER title
        NexusUserFactory(email=user.email, kind=NexusUserKind.GUIDE, source=Service.DORA, auth=Auth.PRO_CONNECT)
        response = client.get(reverse("nexus:homepage"))
        assert pretty_indented(parse_response_to_soup(response, "#header")) == snapshot(name="facility_manager")

        # Only use GUIDE layout if there are only GUIDE kinds
        user.kind = UserKind.PRESCRIBER
        user.save()
        response = client.get(reverse("nexus:homepage"))
        assert pretty_indented(parse_response_to_soup(response, "#header")) == snapshot(name="guide")

        # Ignore NexusUser with empty kind
        NexusUserFactory(email=user.email, kind="", source=Service.COMMUNAUTE, auth=Auth.PRO_CONNECT)
        response = client.get(reverse("nexus:homepage"))
        assert pretty_indented(parse_response_to_soup(response, "#header")) == snapshot(name="guide")

    def test_header_activated_badge(self, client, snapshot):
        user = EmployerFactory(for_snapshot=True)
        company = CompanyMembershipFactory(user=user).company
        client.force_login(user)

        NexusUser.objects.update(source=Service.PILOTAGE)  # disable EMPLOIS service
        response = client.get(reverse("nexus:homepage"))
        assert pretty_indented(parse_response_to_soup(response, "#header")) == snapshot(name="no_badge")

        NexusUserFactory(email=user.email, source=Service.EMPLOIS)
        create_test_romes_and_appellations(["N1101"])
        JobDescriptionFactory(company=company)
        NexusUserFactory(email=user.email, source=Service.DORA)
        response = client.get(reverse("nexus:homepage"))
        assert pretty_indented(parse_response_to_soup(response, "#header")) == snapshot(name="all_badges")

    def test_logout_redirect_url(self, client):
        client.force_login(PrescriberFactory())

        response = client.get(reverse("nexus:homepage"))
        logout_url = add_url_params(reverse("account_logout"), {"redirect_url": reverse("nexus:login")})
        assertContains(response, logout_url)

        response = client.post(logout_url)
        assertRedirects(response, reverse("nexus:login"))


class TestHomePageView:
    url = reverse("nexus:homepage")
    ACTIVATE_SERVICES_H2 = "Mes services actifs"
    NEW_SERVICES_H2 = "Services à découvrir"

    def test_redirect(self, client):
        user = EmployerFactory(membership=True)
        client.force_login(user)
        response = client.get(reverse("nexus:index"))
        assertRedirects(response, self.url, status_code=302)

    def test_one_activated_service(self, client, snapshot):
        user = EmployerFactory(membership=True)
        client.force_login(user)
        response = client.get(self.url)

        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot(name="facility_manager")
        assertContains(response, self.ACTIVATE_SERVICES_H2)
        assertContains(response, self.NEW_SERVICES_H2)

        user.kind = UserKind.PRESCRIBER
        user.save()
        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot(name="guide")

    def test_all_activated_services(self, client, snapshot):
        user = PrescriberFactory()
        for service in Service.activable():
            if service != Service.EMPLOIS:
                NexusUserFactory(email=user.email, source=service, auth=Auth.PRO_CONNECT)
        client.force_login(user)

        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot
        assertContains(response, self.ACTIVATE_SERVICES_H2)
        assertNotContains(response, self.NEW_SERVICES_H2)

    def test_anonymous(self, client):
        # Don't redirect to les emplois default login page
        response = client.get(self.url)
        assertRedirects(response, add_url_params(reverse("nexus:login"), {"next": self.url}))


class TestActivateMonRecapView:
    url = reverse("nexus:activate_mon_recap")

    def test_nominal(self, client):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.post(self.url, follow=True)
        assertRedirects(response, reverse("nexus:mon_recap"))
        assertMessages(
            response,
            [
                messages.Message(
                    messages.SUCCESS,
                    f"Service activé||Vous avez bien activé le service {Service.MON_RECAP.label}",
                    extra_tags="toast",
                )
            ],
        )
        assertQuerySetEqual(
            ActivatedService.objects.all(),
            [(user.pk, Service.MON_RECAP)],
            transform=lambda o: (o.user_id, o.service),
        )

    def test_invalid_method(self, client):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(self.url)
        assert response.status_code == 405


class TestCommunauteView:
    url = reverse("nexus:communaute")

    def test_activated(self, client, snapshot):
        user = PrescriberFactory()
        NexusUserFactory(email=user.email, source=Service.COMMUNAUTE, auth=Auth.PRO_CONNECT)
        client.force_login(user)

        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_not_activated(self, client, snapshot):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_anonymous(self, client):
        # Don't redirect to les emplois default login page
        response = client.get(self.url)
        assertRedirects(response, add_url_params(reverse("nexus:login"), {"next": self.url}))


class TestDoraView:
    url = reverse("nexus:dora")

    def test_activated(self, client, snapshot):
        user = PrescriberFactory()
        NexusUserFactory(email=user.email, source=Service.DORA, auth=Auth.PRO_CONNECT)
        client.force_login(user)

        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_not_activated(self, client, snapshot):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_anonymous(self, client):
        # Don't redirect to les emplois default login page
        response = client.get(self.url)
        assertRedirects(response, add_url_params(reverse("nexus:login"), {"next": self.url}))


class TestEmploisViews:
    url = reverse("nexus:emplois")

    def test_wrong_user_kind(self, client):
        user = PrescriberFactory()
        client.force_login(user)
        response = client.get(self.url)
        assert response.status_code == 403

    def test_no_company(self, client, snapshot):
        user = PrescriberFactory()
        NexusUserFactory(kind=NexusUserKind.FACILITY_MANAGER, email=user.email)
        client.force_login(user)
        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_list(self, client, snapshot):
        user = EmployerFactory()
        company = CompanyMembershipFactory(user=user, company__for_snapshot=True).company
        client.force_login(user)

        other_company = CompanyMembershipFactory(
            user=user, company__kind="EI", company__brand="Le petit mousqueton"
        ).company

        create_test_romes_and_appellations(["N1101"])
        job = JobDescriptionFactory(
            company=company,
            for_snapshot=True,
            last_employer_update_at=timezone.now() - datetime.timedelta(days=10),
        )

        response = client.get(self.url)
        assert (
            pretty_indented(
                parse_response_to_soup(
                    response,
                    "#main",
                    replace_in_attr=[
                        ("href", f"job_description/{job.pk}", "job_description/[PK of JobDescription]"),
                        ("href", str(company.uid), "[Source_ui of NexusStructure]"),
                        ("href", str(other_company.uid), "[Source_ui of other NexusStructure]"),
                        ("value", str(company.pk), "[PK of Company]"),
                        ("value", str(other_company.pk), "[PK of other Company]"),
                    ],
                )
            )
            == snapshot
        )

    def test_anonymous(self, client):
        # Don't redirect to les emplois default login page
        response = client.get(self.url)
        assertRedirects(response, add_url_params(reverse("nexus:login"), {"next": self.url}))


class TestMarcheView:
    url = reverse("nexus:marche")

    def test_activated(self, client, snapshot):
        user = PrescriberFactory()
        NexusUserFactory(email=user.email, source=Service.MARCHE, auth=Auth.PRO_CONNECT)
        client.force_login(user)

        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_not_activated(self, client, snapshot):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_anonymous(self, client):
        # Don't redirect to les emplois default login page
        response = client.get(self.url)
        assertRedirects(response, add_url_params(reverse("nexus:login"), {"next": self.url}))


class TestMonRecapView:
    url = reverse("nexus:mon_recap")

    def test_activated(self, client, snapshot):
        user = PrescriberFactory()
        NexusUserFactory(email=user.email, source=Service.MON_RECAP, auth=Auth.PRO_CONNECT)
        client.force_login(user)

        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_not_activated(self, client, snapshot):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_anonymous(self, client):
        # Don't redirect to les emplois default login page
        response = client.get(self.url)
        assertRedirects(response, add_url_params(reverse("nexus:login"), {"next": self.url}))


class TestPilotageView:
    url = reverse("nexus:pilotage")

    def test_activated(self, client, snapshot):
        user = PrescriberFactory()
        NexusUserFactory(email=user.email, source=Service.PILOTAGE, auth=Auth.PRO_CONNECT)
        client.force_login(user)

        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_not_activated(self, client, snapshot):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_anonymous(self, client):
        # Don't redirect to les emplois default login page
        response = client.get(self.url)
        assertRedirects(response, add_url_params(reverse("nexus:login"), {"next": self.url}))


class TestStructuresView:
    url = reverse("nexus:structures")

    def test_display(self, client, snapshot):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_anonymous(self, client):
        # Don't redirect to les emplois default login page
        response = client.get(self.url)
        assertRedirects(response, add_url_params(reverse("nexus:login"), {"next": self.url}))


class TestContactView:
    url = reverse("nexus:contact")

    def test_display(self, client, snapshot):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(self.url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_anonymous(self, client):
        # Don't redirect to les emplois default login page
        response = client.get(self.url)
        assertRedirects(response, add_url_params(reverse("nexus:login"), {"next": self.url}))


class TestLoginView:
    def test_authenticated(self, client):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(reverse("nexus:login"))
        assertRedirects(response, reverse("nexus:homepage"))

    def test_anonymous(self, client, pro_connect, snapshot):
        response = client.get(reverse("nexus:login"))
        soup = parse_response_to_soup(response, "#main")
        for a_tags in soup.find_all("a", attrs={"href": True}):
            if a_tags["href"].startswith("/static/pdf/syntheseSecurite"):
                a_tags["href"] = "/static/pdf/syntheseSecurite.pdf"  # Normalize href for CI
        assert pretty_indented(soup) == snapshot
