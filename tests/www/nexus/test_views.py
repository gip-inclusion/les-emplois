import datetime
import random

from django.conf import settings
from django.contrib import messages
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from itoutils.urls import add_url_params
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.nexus.enums import Auth, NexusUserKind, Service
from itou.nexus.models import NexusUser
from tests.companies.factories import CompanyMembershipFactory, JobDescriptionFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.nexus.factories import NexusUserFactory
from tests.users.factories import EmployerFactory, PrescriberFactory
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
        client.force_login(user)
        response = client.get(reverse("nexus:homepage"))

        soup = parse_response_to_soup(response, "#footer")
        for a_tags in soup.find_all("a", attrs={"href": True}):
            if a_tags["href"].startswith("/static/pdf/syntheseSecurite"):
                a_tags["href"] = "/static/pdf/syntheseSecurite.pdf"  # Normalize href for CI
        assert pretty_indented(soup) == snapshot

    def test_header_titles(self, client, snapshot):
        user = EmployerFactory(for_snapshot=True, membership=True)
        client.force_login(user)

        # If there's only FACILITY_MANAGER kinds
        assert NexusUser.objects.get().kind == NexusUserKind.FACILITY_MANAGER
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


class TestHomePageView:
    url = reverse("nexus:homepage")
    ACTIVATE_SERVICES_H2 = "Mes services actifs"
    NEW_SERVICES_H2 = "Services à découvrir"

    def test_one_activated_service(self, client, snapshot):
        user = EmployerFactory(membership=True)
        nexus_user = NexusUser.objects.get()
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
            if service != Service.EMPLOIS:
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
        NexusUser.objects.update(source=Service.DORA)
        client.force_login(user)

        client.get(self.url)
        assert caplog.messages == [f"User is missing it's NexusUser user={user.pk}", "HTTP 200 OK"]


class TestActivateView:
    def test_nominal(self, client):
        user = PrescriberFactory()
        client.force_login(user)

        service = random.choice([Service.PILOTAGE, Service.MON_RECAP])
        response = client.post(reverse("nexus:activate", args=(service,)), follow=True)
        next_url = reverse("nexus:pilotage") if service == Service.PILOTAGE else reverse("nexus:mon_recap")
        assertRedirects(response, next_url)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.SUCCESS,
                    f"Service activé||Vous avez bien activé le service {service.label}",
                    extra_tags="toast",
                )
            ],
        )
        assert NexusUser.objects.filter(source_id=user.pk, source=service)

    def test_invalid_service(self, client):
        user = PrescriberFactory()
        client.force_login(user)

        service = random.choice(
            [
                Service.EMPLOIS,
                Service.DORA,
                Service.MARCHE,
                Service.COMMUNAUTE,
                Service.DATA_INCLUSION,
                "some-random-string",
            ]
        )
        response = client.get(reverse("nexus:activate", args=(service,)))
        assert response.status_code == 404

    def test_invalid_method(self, client):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(reverse("nexus:activate", args=(Service.MON_RECAP,)))
        assert response.status_code == 404


class TestCommunauteView:
    def test_activated(self, client, snapshot):
        user = PrescriberFactory()
        NexusUserFactory(email=user.email, source=Service.COMMUNAUTE, auth=Auth.PRO_CONNECT)
        client.force_login(user)

        response = client.get(reverse("nexus:communaute"))
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_not_activated(self, client, snapshot):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(reverse("nexus:communaute"))
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot


class TestDoraView:
    def test_activated(self, client, snapshot):
        user = PrescriberFactory()
        NexusUserFactory(email=user.email, source=Service.DORA, auth=Auth.PRO_CONNECT)
        client.force_login(user)

        response = client.get(reverse("nexus:dora"))
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_not_activated(self, client, snapshot):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(reverse("nexus:dora"))
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot


class TestEmploisViews:
    def test_not_activated(self, client, snapshot):
        user = PrescriberFactory()
        NexusUser.objects.update(source=Service.DORA)
        client.force_login(user)

        response = client.get(reverse("nexus:emplois"))
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_list(self, client, snapshot):
        user = EmployerFactory()
        company = CompanyMembershipFactory(user=user, company__for_snapshot=True).company
        client.force_login(user)

        create_test_romes_and_appellations(["N1101"])
        job = JobDescriptionFactory(
            company=company,
            for_snapshot=True,
            last_employer_update_at=timezone.now() - datetime.timedelta(days=10),
        )

        response = client.get(reverse("nexus:emplois"))
        assert (
            pretty_indented(
                parse_response_to_soup(
                    response,
                    "#main",
                    replace_in_attr=[
                        ("href", f"job_description/{job.pk}", "job_description/[PK of JobDescription]"),
                    ],
                )
            )
            == snapshot
        )


class TestMarcheView:
    def test_activated(self, client, snapshot):
        user = PrescriberFactory()
        NexusUserFactory(email=user.email, source=Service.MARCHE, auth=Auth.PRO_CONNECT)
        client.force_login(user)

        response = client.get(reverse("nexus:marche"))
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_not_activated(self, client, snapshot):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(reverse("nexus:marche"))
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot


class TestMonRecapView:
    def test_activated(self, client, snapshot):
        user = PrescriberFactory()
        NexusUserFactory(email=user.email, source=Service.MON_RECAP, auth=Auth.PRO_CONNECT)
        client.force_login(user)

        response = client.get(reverse("nexus:mon_recap"))
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_not_activated(self, client, snapshot):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(reverse("nexus:mon_recap"))
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot


class TestPilotageView:
    def test_activated(self, client, snapshot):
        user = PrescriberFactory()
        NexusUserFactory(email=user.email, source=Service.PILOTAGE, auth=Auth.PRO_CONNECT)
        client.force_login(user)

        response = client.get(reverse("nexus:pilotage"))
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

    def test_not_activated(self, client, snapshot):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(reverse("nexus:pilotage"))
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot


class TestStructuresView:
    def test_display(self, client, snapshot):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(reverse("nexus:structures"))
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot
