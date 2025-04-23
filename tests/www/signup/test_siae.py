import httpx
import respx
from django.contrib import messages
from django.urls import reverse
from django.utils.html import escape
from django.utils.http import urlencode
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertRedirects

from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.users.enums import KIND_EMPLOYER, UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.mocks.api_entreprise import ETABLISSEMENT_API_RESULT_MOCK, INSEE_API_RESULT_MOCK
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK
from itou.utils.templatetags.format_filters import format_siret
from itou.utils.urls import get_tally_form_url
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory, CompanyWithMembershipAndJobsFactory
from tests.users.factories import DEFAULT_PASSWORD, EmployerFactory, PrescriberFactory
from tests.utils.test import ItouClient, assertSnapshotQueries


class TestCompanySignup:
    def test_choose_user_kind(self, client):
        url = reverse("signup:choose_user_kind")
        response = client.get(url)
        assertContains(response, "Employeur inclusif")

        response = client.post(url, data={"kind": UserKind.EMPLOYER})
        assertRedirects(response, reverse("signup:company_select"))

    @freeze_time("2022-09-15 15:53:54")
    @respx.mock
    def test_join_an_company_without_members(self, client, mailoutbox, pro_connect):
        """
        A user joins a company without members.
        """
        company = CompanyFactory(kind=CompanyKind.ETTI)
        assert 0 == company.members.count()

        url = reverse("signup:company_select")
        response = client.get(url)
        assert response.status_code == 200

        # Find a company by SIREN.
        response = client.get(url, {"siren": company.siret[:9]})
        assert response.status_code == 200

        # Choose a company between results.
        post_data = {"siaes": company.pk}
        # Pass `siren` in request.GET
        response = client.post(f"{url}?siren={company.siret[:9]}", data=post_data)
        assert response.status_code == 302
        assertRedirects(response, reverse("search:employers_home"))

        assert len(mailoutbox) == 1
        email = mailoutbox[0]
        assert "Un nouvel utilisateur souhaite rejoindre votre structure" in email.subject

        magic_link = company.signup_magic_link
        response = client.get(magic_link)
        assert response.status_code == 200

        # No error when opening magic link a second time.
        response = client.get(magic_link)
        pro_connect.assertContainsButton(response)

        # Check IC will redirect to the correct url
        token = company.get_token()
        previous_url = reverse("signup:employer", args=(company.pk, token))
        next_url = reverse("signup:company_join", args=(company.pk, token))
        params = {
            "user_kind": KIND_EMPLOYER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            KIND_EMPLOYER,
            previous_url=previous_url,
            next_url=next_url,
        )
        response = client.get(response.url)
        # Check user is redirected to the welcoming tour
        assertRedirects(response, reverse("welcoming_tour:index"))
        # Check user sees the employer tour
        response = client.get(response.url)
        assertContains(response, "Publiez vos offres, augmentez votre visibilité")

        user = User.objects.get(email=pro_connect.oidc_userinfo["email"])

        # Check `User` state.
        assert user.kind == UserKind.EMPLOYER
        assert user.is_active
        assert company.has_admin(user)
        assert 1 == company.members.count()

        # No new sent email.
        assert len(mailoutbox) == 1

        # Magic link is no longer valid because company.members.count() has changed.
        response = client.get(magic_link, follow=True)
        assertRedirects(response, reverse("signup:company_select"))
        expected_message = (
            "Ce lien d'inscription est invalide ou a expiré. Veuillez procéder à une nouvelle inscription."
        )
        assertContains(response, escape(expected_message))

    def test_join_company_with_member(self, client):
        company = CompanyFactory(kind=CompanyKind.ETTI, with_membership=True, for_snapshot=True)
        assert company.members.count() > 0

        url = reverse("signup:company_select")
        response = client.get(url)
        assert response.status_code == 200

        # Find a company by SIREN.
        response = client.get(url, {"siren": company.siret[:9]})
        assert response.status_code == 200
        assertContains(response, " Pour rejoindre cette structure, <b>veuillez contacter John D.</b>")

        # Choose a company between results.
        # Joining without invitation is impossible.
        post_data = {"siaes": company.pk}
        response = client.post(f"{url}?siren={company.siret[:9]}", data=post_data)
        assert response.status_code == 200

    @freeze_time("2022-09-15 15:53:54")
    @respx.mock
    def test_join_an_company_without_members_as_an_existing_employer(self, client, pro_connect):
        """
        A user joins a company without members.
        """
        company = CompanyFactory(kind=CompanyKind.ETTI)
        assert 0 == company.members.count()

        user = EmployerFactory(
            username=pro_connect.oidc_userinfo["sub"],
            email=pro_connect.oidc_userinfo["email"],
            has_completed_welcoming_tour=True,
        )
        CompanyMembershipFactory(user=user)
        assert 1 == user.company_set.count()

        magic_link = company.signup_magic_link
        response = client.get(magic_link)
        pro_connect.assertContainsButton(response)

        # Check IC will redirect to the correct url
        token = company.get_token()
        previous_url = reverse("signup:employer", args=(company.pk, token))
        next_url = reverse("signup:company_join", args=(company.pk, token))
        params = {
            "user_kind": KIND_EMPLOYER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            KIND_EMPLOYER,
            previous_url=previous_url,
            next_url=next_url,
        )
        response = client.get(response.url)
        # Check user is redirected to the dashboard
        assertRedirects(response, reverse("dashboard:index"))

        # Check `User` state.
        assert company.has_admin(user)
        assert 1 == company.members.count()
        assert 2 == user.company_set.count()

    @freeze_time("2022-09-15 15:53:54")
    @respx.mock
    def test_join_an_company_without_members_as_an_existing_employer_returns_on_other_browser(
        self, client, pro_connect
    ):
        """
        A user joins a company without members.
        """
        company = CompanyFactory(kind=CompanyKind.ETTI)

        user = EmployerFactory(
            username=pro_connect.oidc_userinfo["sub"],
            email=pro_connect.oidc_userinfo["email"],
            has_completed_welcoming_tour=True,
        )
        CompanyMembershipFactory(user=user)

        magic_link = company.signup_magic_link
        response = client.get(magic_link)
        pro_connect.assertContainsButton(response)

        # Check IC will redirect to the correct url
        token = company.get_token()
        previous_url = reverse("signup:employer", args=(company.pk, token))
        next_url = reverse("signup:company_join", args=(company.pk, token))
        params = {
            "user_kind": KIND_EMPLOYER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        other_client = ItouClient()
        response = pro_connect.mock_oauth_dance(
            client,
            KIND_EMPLOYER,
            previous_url=previous_url,
            next_url=next_url,
            other_client=other_client,
        )
        response = other_client.get(response.url)
        # Check user is redirected to the dashboard
        assertRedirects(response, reverse("dashboard:index"))

        # Check `User` state.
        assert company.has_admin(user)
        assert 1 == company.members.count()
        assert 2 == user.company_set.count()

    def test_user_invalid_company_id(self, client):
        company = CompanyFactory(kind=CompanyKind.ETTI)
        response = client.get(reverse("signup:employer", kwargs={"company_id": "0", "token": company.get_token()}))
        assertRedirects(response, reverse("signup:company_select"))
        assertMessages(
            response,
            [
                messages.Message(
                    messages.WARNING,
                    "Ce lien d'inscription est invalide ou a expiré. Veuillez procéder à une nouvelle inscription.",
                )
            ],
        )

    def test_join_invalid_company_id(self, client):
        user = EmployerFactory(with_company=True)
        client.force_login(user)
        company = CompanyFactory(kind=CompanyKind.ETTI)
        response = client.get(
            reverse("signup:company_join", kwargs={"company_id": "0", "token": company.get_token()}), follow=True
        )
        assertRedirects(response, reverse("signup:company_select"))
        assertMessages(
            response,
            [
                messages.Message(
                    messages.WARNING,
                    "Ce lien d'inscription est invalide ou a expiré. Veuillez procéder à une nouvelle inscription.",
                )
            ],
        )

    @respx.mock
    def test_create_facilitator(self, client, mocker, mailoutbox, settings, pro_connect):
        settings.API_INSEE_BASE_URL = "https://insee.fake"
        settings.API_INSEE_SIRENE_BASE_URL = "https://entreprise.fake"
        settings.API_INSEE_CONSUMER_KEY = "foo"
        settings.API_INSEE_CONSUMER_SECRET = "bar"
        mock_call_ban_geocoding_api = mocker.patch(
            "itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK
        )
        respx.post(f"{settings.API_INSEE_BASE_URL}/token").mock(
            return_value=httpx.Response(200, json=INSEE_API_RESULT_MOCK)
        )

        FAKE_SIRET = "26570134200148"  # matches the one from ETABLISSEMENT_API_RESULT_MOCK for consistency

        url = reverse("signup:facilitator_search")
        post_data = {
            "siret": FAKE_SIRET,
        }

        # Mocks an invalid answer from the server
        respx.get(f"{settings.API_INSEE_SIRENE_BASE_URL}/siret/{FAKE_SIRET}").mock(
            return_value=httpx.Response(404, json={})
        )
        response = client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_not_called()
        assertContains(response, f"SIRET « {FAKE_SIRET} » non reconnu.")

        # Mock a valid answer from the server
        respx.get(f"{settings.API_INSEE_SIRENE_BASE_URL}/siret/{FAKE_SIRET}").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )
        response = client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_called_once()
        assertRedirects(response, reverse("signup:facilitator_user"))

        # Checks that the SIRET and  the enterprise name are present in the second step
        response = client.post(url, data=post_data, follow=True)
        assertContains(response, "Centre communal")
        assertContains(response, format_siret(FAKE_SIRET))

        # Now, we're on the second page.
        url = reverse("signup:facilitator_user")
        pro_connect.assertContainsButton(response)

        # Check IC will redirect to the correct url
        previous_url = reverse("signup:facilitator_user")
        next_url = reverse("signup:facilitator_join")
        params = {
            "user_kind": KIND_EMPLOYER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            KIND_EMPLOYER,
            previous_url=previous_url,
            next_url=next_url,
        )
        response = client.get(response.url)
        # Check user is redirected to the welcoming tour
        assertRedirects(response, reverse("welcoming_tour:index"))
        # Check user sees the employer tour
        response = client.get(response.url)
        assertContains(response, "Publiez vos offres, augmentez votre visibilité")

        user = User.objects.get(email=pro_connect.oidc_userinfo["email"])

        # Check `User` state.
        assert user.kind == UserKind.EMPLOYER
        assert user.is_active
        company = Company.objects.get(siret=FAKE_SIRET)
        assert company.has_admin(user)
        assert 1 == company.members.count()

        # No sent email.
        assert len(mailoutbox) == 0

    def test_facilitator_base_signup_process(self, client):
        url = reverse("signup:company_select")
        response = client.get(url, {"siren": "111111111"})  # not existing SIREN
        assertContains(response, global_constants.ITOU_HELP_CENTER_URL)
        assertContains(response, get_tally_form_url("wA799W"))
        assertContains(response, reverse("signup:facilitator_search"))

    def test_company_select_does_not_die_under_requests(self, client, snapshot):
        companies = (
            CompanyWithMembershipAndJobsFactory(siret="40219166200001"),
            CompanyWithMembershipAndJobsFactory(siret="40219166200002"),
            CompanyWithMembershipAndJobsFactory(siret="40219166200003"),
            CompanyWithMembershipAndJobsFactory(siret="40219166200004"),
            CompanyWithMembershipAndJobsFactory(siret="40219166200005"),
            CompanyWithMembershipAndJobsFactory(siret="40219166200005", kind=CompanyKind.AI),
        )
        # Add more than one member to all company to test prefetch and distinct
        for company in companies:
            CompanyMembershipFactory.create_batch(2, company=company)

        url = reverse("signup:company_select")
        # ensure we only perform 4 requests, whatever the number of companies sharing the
        # same SIREN. Before, this request was issuing 3*N slow requests, N being the
        # number of companies.
        with assertSnapshotQueries(snapshot):
            response = client.get(url, {"siren": "402191662"})
        assert response.status_code == 200
        assertContains(response, "402191662", count=7)  # 1 input + 6 results
        assertContains(response, "00001", count=1)
        assertContains(response, "00002", count=1)
        assertContains(response, "00003", count=1)
        assertContains(response, "00004", count=1)
        assertContains(response, "00005", count=2)


def test_non_staff_cant_join_a_company(client):
    company = CompanyFactory(kind=CompanyKind.ETTI)
    assert 0 == company.members.count()

    user = PrescriberFactory()
    client.login(email=user.email, password=DEFAULT_PASSWORD)

    # Skip IC process and jump to joining the company.
    token = company.get_token()
    url = reverse("signup:company_join", args=(company.pk, token))

    response = client.get(url)
    assertMessages(
        response,
        [
            messages.Message(
                messages.ERROR,
                "Vous ne pouvez pas rejoindre une structure avec ce compte car vous n'êtes pas employeur.",
            )
        ],
    )
    assertRedirects(response, reverse("search:employers_home"))

    # Check `User` state.
    assert not company.has_admin(user)
    assert 0 == company.members.count()
