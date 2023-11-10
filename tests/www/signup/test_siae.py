from unittest import mock

import httpx
import pytest
import respx
from django.conf import settings
from django.contrib import messages
from django.core import mail
from django.test import Client, override_settings
from django.urls import reverse
from django.utils.html import escape
from django.utils.http import urlencode
from freezegun import freeze_time

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
from tests.openid_connect.inclusion_connect.test import InclusionConnectBaseTestCase
from tests.openid_connect.inclusion_connect.tests import OIDC_USERINFO, mock_oauth_dance
from tests.users.factories import DEFAULT_PASSWORD, EmployerFactory, PrescriberFactory
from tests.utils.test import BASE_NUM_QUERIES, TestCase, assertMessages


pytestmark = pytest.mark.ignore_template_errors


class SiaeSignupTest(InclusionConnectBaseTestCase):
    def test_choose_user_kind(self):
        url = reverse("signup:choose_user_kind")
        response = self.client.get(url)
        self.assertContains(response, "Employeur solidaire")

        response = self.client.post(url, data={"kind": UserKind.EMPLOYER})
        self.assertRedirects(response, reverse("signup:company_select"))

    @freeze_time("2022-09-15 15:53:54")
    @respx.mock
    def test_join_an_siae_without_members(self):
        """
        A user joins an SIAE without members.
        """
        company = CompanyFactory(kind=CompanyKind.ETTI)
        assert 0 == company.members.count()

        url = reverse("signup:company_select")
        response = self.client.get(url)
        assert response.status_code == 200

        # Find an SIAE by SIREN.
        response = self.client.get(url, {"siren": company.siret[:9]})
        assert response.status_code == 200

        # Choose an SIAE between results.
        post_data = {"siaes": company.pk}
        # Pass `siren` in request.GET
        response = self.client.post(f"{url}?siren={company.siret[:9]}", data=post_data)
        assert response.status_code == 302
        self.assertRedirects(response, reverse("search:siaes_home"))

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert "Un nouvel utilisateur souhaite rejoindre votre structure" in email.subject

        magic_link = company.signup_magic_link
        response = self.client.get(magic_link)
        assert response.status_code == 200

        # No error when opening magic link a second time.
        response = self.client.get(magic_link)
        self.assertContains(response, "logo-inclusion-connect-one-line.svg")

        # Check IC will redirect to the correct url
        token = company.get_token()
        previous_url = reverse("signup:employer", args=(company.pk, token))
        next_url = reverse("signup:company_join", args=(company.pk, token))
        params = {
            "user_kind": KIND_EMPLOYER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        response = mock_oauth_dance(
            self.client,
            KIND_EMPLOYER,
            previous_url=previous_url,
            next_url=next_url,
        )
        response = self.client.get(response.url)
        # Check user is redirected to the welcoming tour
        self.assertRedirects(response, reverse("welcoming_tour:index"))
        # Check user sees the employer tour
        response = self.client.get(response.url)
        self.assertContains(response, "Publiez vos offres, augmentez votre visibilité")

        user = User.objects.get(email=OIDC_USERINFO["email"])

        # Check `User` state.
        assert user.kind == UserKind.EMPLOYER
        assert user.is_active
        assert company.has_admin(user)
        assert 1 == company.members.count()

        # No new sent email.
        assert len(mail.outbox) == 1

        # Magic link is no longer valid because siae.members.count() has changed.
        response = self.client.get(magic_link, follow=True)
        self.assertRedirects(response, reverse("signup:company_select"))
        expected_message = (
            "Ce lien d'inscription est invalide ou a expiré. Veuillez procéder à une nouvelle inscription."
        )
        self.assertContains(response, escape(expected_message))

    @freeze_time("2022-09-15 15:53:54")
    @respx.mock
    def test_join_an_siae_without_members_as_an_existing_employer(self):
        """
        A user joins an SIAE without members.
        """
        company = CompanyFactory(kind=CompanyKind.ETTI)
        assert 0 == company.members.count()

        user = EmployerFactory(email=OIDC_USERINFO["email"], has_completed_welcoming_tour=True)
        CompanyMembershipFactory(user=user)
        assert 1 == user.company_set.count()

        magic_link = company.signup_magic_link
        response = self.client.get(magic_link)
        self.assertContains(response, "logo-inclusion-connect-one-line.svg")

        # Check IC will redirect to the correct url
        token = company.get_token()
        previous_url = reverse("signup:employer", args=(company.pk, token))
        next_url = reverse("signup:company_join", args=(company.pk, token))
        params = {
            "user_kind": KIND_EMPLOYER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        response = mock_oauth_dance(
            self.client,
            KIND_EMPLOYER,
            previous_url=previous_url,
            next_url=next_url,
        )
        response = self.client.get(response.url)
        # Check user is redirected to the dashboard
        self.assertRedirects(response, reverse("dashboard:index"))

        # Check `User` state.
        assert company.has_admin(user)
        assert 1 == company.members.count()
        assert 2 == user.company_set.count()

    @freeze_time("2022-09-15 15:53:54")
    @respx.mock
    def test_join_an_siae_without_members_as_an_existing_employer_returns_on_other_browser(self):
        """
        A user joins an SIAE without members.
        """
        company = CompanyFactory(kind=CompanyKind.ETTI)

        user = EmployerFactory(email=OIDC_USERINFO["email"], has_completed_welcoming_tour=True)
        CompanyMembershipFactory(user=user)

        magic_link = company.signup_magic_link
        response = self.client.get(magic_link)
        self.assertContains(response, "logo-inclusion-connect-one-line.svg")

        # Check IC will redirect to the correct url
        token = company.get_token()
        previous_url = reverse("signup:employer", args=(company.pk, token))
        next_url = reverse("signup:company_join", args=(company.pk, token))
        params = {
            "user_kind": KIND_EMPLOYER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        other_client = Client()
        response = mock_oauth_dance(
            self.client,
            KIND_EMPLOYER,
            previous_url=previous_url,
            next_url=next_url,
            other_client=other_client,
        )
        response = other_client.get(response.url)
        # Check user is redirected to the dashboard
        self.assertRedirects(response, reverse("dashboard:index"))

        # Check `User` state.
        assert company.has_admin(user)
        assert 1 == company.members.count()
        assert 2 == user.company_set.count()

    def test_user_invalid_siae_id(self):
        company = CompanyFactory(kind=CompanyKind.ETTI)
        response = self.client.get(
            reverse("signup:employer", kwargs={"company_id": "0", "token": company.get_token()})
        )
        self.assertRedirects(response, reverse("signup:company_select"))
        assertMessages(
            response,
            [
                (
                    messages.WARNING,
                    "Ce lien d'inscription est invalide ou a expiré. Veuillez procéder à une nouvelle inscription.",
                )
            ],
        )

    def test_join_invalid_siae_id(self):
        user = EmployerFactory(with_company=True)
        self.client.force_login(user)
        company = CompanyFactory(kind=CompanyKind.ETTI)
        response = self.client.get(
            reverse("signup:company_join", kwargs={"company_id": "0", "token": company.get_token()}), follow=True
        )
        self.assertRedirects(response, reverse("signup:company_select"))
        assertMessages(
            response,
            [
                (
                    messages.WARNING,
                    "Ce lien d'inscription est invalide ou a expiré. Veuillez procéder à une nouvelle inscription.",
                )
            ],
        )

    @respx.mock
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    @override_settings(
        API_INSEE_BASE_URL="https://insee.fake",
        API_INSEE_SIRENE_BASE_URL="https://entreprise.fake",
        API_INSEE_CONSUMER_KEY="foo",
        API_INSEE_CONSUMER_SECRET="bar",
    )
    def test_create_facilitator(self, mock_call_ban_geocoding_api):
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
        response = self.client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_not_called()
        self.assertContains(response, f"SIRET « {FAKE_SIRET} » non reconnu.")

        # Mock a valid answer from the server
        respx.get(f"{settings.API_INSEE_SIRENE_BASE_URL}/siret/{FAKE_SIRET}").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )
        response = self.client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_called_once()
        self.assertRedirects(response, reverse("signup:facilitator_user"))

        # Checks that the SIRET and  the enterprise name are present in the second step
        response = self.client.post(url, data=post_data, follow=True)
        self.assertContains(response, "Centre communal")
        self.assertContains(response, format_siret(FAKE_SIRET))

        # Now, we're on the second page.
        url = reverse("signup:facilitator_user")
        self.assertContains(response, "logo-inclusion-connect-one-line.svg")

        # Check IC will redirect to the correct url
        previous_url = reverse("signup:facilitator_user")
        next_url = reverse("signup:facilitator_join")
        params = {
            "user_kind": KIND_EMPLOYER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        response = mock_oauth_dance(
            self.client,
            KIND_EMPLOYER,
            previous_url=previous_url,
            next_url=next_url,
        )
        response = self.client.get(response.url)
        # Check user is redirected to the welcoming tour
        self.assertRedirects(response, reverse("welcoming_tour:index"))
        # Check user sees the employer tour
        response = self.client.get(response.url)
        self.assertContains(response, "Publiez vos offres, augmentez votre visibilité")

        user = User.objects.get(email=OIDC_USERINFO["email"])

        # Check `User` state.
        assert user.kind == UserKind.EMPLOYER
        assert user.is_active
        siae = Company.objects.get(siret=FAKE_SIRET)
        assert siae.has_admin(user)
        assert 1 == siae.members.count()

        # No sent email.
        assert len(mail.outbox) == 0

    def test_facilitator_base_signup_process(self):
        url = reverse("signup:company_select")
        response = self.client.get(url, {"siren": "111111111"})  # not existing SIREN
        self.assertContains(response, global_constants.ITOU_HELP_CENTER_URL)
        self.assertContains(response, get_tally_form_url("wA799W"))
        self.assertContains(response, reverse("signup:facilitator_search"))

    def test_siae_select_does_not_die_under_requests(self):
        companies = (
            CompanyWithMembershipAndJobsFactory(siret="40219166200001"),
            CompanyWithMembershipAndJobsFactory(siret="40219166200002"),
            CompanyWithMembershipAndJobsFactory(siret="40219166200003"),
            CompanyWithMembershipAndJobsFactory(siret="40219166200004"),
            CompanyWithMembershipAndJobsFactory(siret="40219166200005"),
            CompanyWithMembershipAndJobsFactory(siret="40219166200005", kind=CompanyKind.AI),
        )
        # Add more than one member to all SIAE to test prefetch and distinct
        for company in companies:
            CompanyMembershipFactory.create_batch(2, company=company)

        url = reverse("signup:company_select")
        # ensure we only perform 4 requests, whatever the number of SIAEs sharing the
        # same SIREN. Before, this request was issuing 3*N slow requests, N being the
        # number of SIAEs.
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # SELECT siaes with active admins
            + 1  # SELECT the conventions for those siaes
            + 1  # prefetch memberships
            + 1  # prefetch users associated with those memberships
        ):
            response = self.client.get(url, {"siren": "402191662"})
        assert response.status_code == 200
        self.assertContains(response, "402191662", count=7)  # 1 input + 6 results
        self.assertContains(response, "00001", count=1)
        self.assertContains(response, "00002", count=1)
        self.assertContains(response, "00003", count=1)
        self.assertContains(response, "00004", count=1)
        self.assertContains(response, "00005", count=2)


class SiaeSignupViewsExceptionsTest(TestCase):
    def test_non_staff_cant_join_a_siae(self):
        company = CompanyFactory(kind=CompanyKind.ETTI)
        assert 0 == company.members.count()

        user = PrescriberFactory(email=OIDC_USERINFO["email"])
        self.client.login(email=user.email, password=DEFAULT_PASSWORD)

        # Skip IC process and jump to joining the SIAE.
        token = company.get_token()
        url = reverse("signup:company_join", args=(company.pk, token))

        response = self.client.get(url)
        assertMessages(
            response,
            [
                (
                    messages.ERROR,
                    "Vous ne pouvez pas rejoindre une structure avec ce compte car vous n'êtes pas employeur.",
                )
            ],
        )
        self.assertRedirects(response, reverse("search:siaes_home"))

        # Check `User` state.
        assert not company.has_admin(user)
        assert 0 == company.members.count()
