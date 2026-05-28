import random

import httpx
import pytest
import respx
from django.contrib import messages
from django.urls import reverse
from django.utils.html import escape
from django.utils.http import urlencode
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from itoutils.urls import add_url_params
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.companies.enums import CompanyKind
from itou.companies.models import Company, CompanyMembership
from itou.users.enums import IdentityProvider
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.mocks.api_entreprise import ETABLISSEMENT_API_RESULT_MOCK, INSEE_API_RESULT_MOCK
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK
from itou.utils.urls import get_tally_form_url, get_zendesk_form_url
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.users.factories import JobSeekerFactory, random_pro_user_factory
from tests.utils.testing import accept_legal_terms, parse_response_to_soup, pretty_indented


class TestCompanySignup:
    @staticmethod
    def to_join_msg(admin_user):
        return (
            " Pour rejoindre cette structure, <b>veuillez contacter "
            f"{admin_user.first_name.title()} {admin_user.last_name[0].upper()}.</b>"
        )

    @pytest.mark.parametrize(
        "scenario",
        ["no_member", "no_active_member"],
    )
    @freeze_time("2024-09-15 15:53:54")
    def test_join_an_company_without_active_members(self, client, mailoutbox, pro_connect, scenario):
        """
        A user joins a company without active members.

        There are two ways for a user to be an inactive member of a company:
        - as a user (see AbstractUser.is_active).
        - as a member of a company (see MembershipAbstract.is_active).

        """
        user = random_pro_user_factory(identity_provider=IdentityProvider.PRO_CONNECT)
        client.force_login(user)

        company = CompanyFactory(kind=CompanyKind.ETTI)
        company_active_members_qs = CompanyMembership.objects.filter(company=company.pk)
        url = reverse("signup:company_select")

        if scenario == "no_member":
            assert company.members.count() == 0
        elif scenario == "no_active_member":
            # Active member but we make the membership inactive.
            CompanyMembershipFactory(company=company, is_active=False, user__is_active=True)
            # Active membership but we make the member inactive.
            CompanyMembershipFactory(company=company, is_active=True, user__is_active=False)
            assert company.members.count() == 2

        assert company_active_members_qs.count() == 0  # Make sure there is no active user.

        response = client.get(url)
        assert response.status_code == 200

        # Find a company by SIREN.
        response = client.get(url, {"siren": company.siret[:9]})
        assert response.status_code == 200

        # Choose a company between results.
        post_data = {"siaes": company.pk}
        # Pass `siren` in request.GET
        response = client.post(f"{url}?siren={company.siret[:9]}", data=post_data, follow=True)
        assertRedirects(response, reverse("logout:warning", kwargs={"kind": "no_organization"}))

        assert len(mailoutbox) == 1
        email = mailoutbox[0]
        assert "Un nouvel utilisateur souhaite rejoindre votre structure" in email.subject

        magic_link = company.signup_magic_link
        response = client.get(magic_link)
        token = company.get_token()
        next_url = reverse("signup:company_join", args=(company.pk, token))
        assertRedirects(response, next_url, fetch_redirect_response=False)

        response = client.get(response.url, follow=True)
        # Check user is redirected to the welcoming tour
        assertRedirects(response, reverse("welcoming_tour:index"))
        # Check user sees the employer tour
        assertContains(response, "Publiez vos offres, augmentez votre visibilité")

        # Check `User` state.
        user.refresh_from_db()
        assert user.is_active
        assert company.has_admin(user)
        assert company_active_members_qs.count() == 1  # Make sure there is one active user after registration.

        # No new sent email.
        assert len(mailoutbox) == 1

        # Magic link is no longer valid because company.members.count() has changed.
        response = client.get(magic_link, follow=True)
        assertRedirects(response, reverse("signup:company_select"))
        expected_message = (
            "Ce lien d'inscription est invalide ou a expiré. Veuillez procéder à une nouvelle inscription."
        )
        assertContains(response, escape(expected_message))

    @freeze_time("2024-09-15 15:53:54")
    def test_join_a_company_without_members_but_invalid_auth_email(self, client, mailoutbox):
        user = random_pro_user_factory()
        client.force_login(user)

        company = CompanyFactory(kind=CompanyKind.OPCS, auth_email="Non renseigné")
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
        assert response.status_code == 200
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    (
                        "L’adresse e-mail de contact du gestionnaire de cette structure n’est pas renseignée. Merci "
                        f'de <a href="{get_zendesk_form_url(response.wsgi_request)}" target="_blank" rel="noopener" '
                        'class="has-external-link">contacter notre support technique</a> afin de poursuivre votre'
                        "inscription."
                    ),
                )
            ],
        )
        assert len(mailoutbox) == 0

    def test_join_company_with_active_member(self, client):
        user = random_pro_user_factory()
        client.force_login(user)

        company = CompanyFactory(kind=CompanyKind.ETTI, with_membership=True, for_snapshot=True)
        assert company.members.count() > 0

        url = reverse("signup:company_select")
        response = client.get(url)
        assert response.status_code == 200

        # Find a company by SIREN.
        response = client.get(url, {"siren": company.siret[:9]})
        assert response.status_code == 200
        assertContains(response, self.to_join_msg(company.members.get()))

        # Choose a company between results.
        # Joining without invitation is impossible.
        post_data = {"siaes": company.pk}
        response = client.post(f"{url}?siren={company.siret[:9]}", data=post_data)
        assert response.status_code == 200
        assert response.context["company_select_form"].errors == {
            "siaes": ["Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles."]
        }

    @freeze_time("2024-09-15 15:53:54")
    def test_join_a_company_without_members_as_an_existing_employer(self, client, pro_connect):
        company = CompanyFactory(kind=CompanyKind.ETTI)
        assert 0 == company.members.count()

        user = random_pro_user_factory(
            username=pro_connect.oidc_userinfo["sub"],
            email=pro_connect.oidc_userinfo["email"],
            has_completed_welcoming_tour=True,
            identity_provider=IdentityProvider.PRO_CONNECT,
        )
        old_company = CompanyMembershipFactory(user=user).company
        assert 1 == user.company_set.count()

        client.force_login(user)
        client.get(reverse("dashboard:index"))
        assert (
            client.session.get(global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY)
            == old_company.organization_switch_key
        )

        magic_link = company.signup_magic_link
        response = client.get(magic_link, follow=True)
        assertRedirects(response, reverse("dashboard:index"))

        # Check `User` state.
        assert company.has_admin(user)
        assert 1 == company.members.count()
        assert 2 == user.company_set.count()
        assert (
            client.session.get(global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY)
            == company.organization_switch_key
        )

    @freeze_time("2024-09-15 15:53:54")
    def test_join_a_company_without_members_logged_out(self, client, pro_connect):
        """
        A user joins a company without members.
        """
        company = CompanyFactory(kind=CompanyKind.ETTI)

        magic_link = company.signup_magic_link
        response = client.get(magic_link)
        pro_connect.assertContainsButton(response)

        # Check ProConnect will redirect to the correct url
        token = company.get_token()
        previous_url = reverse("signup:employer", args=(company.pk, token))
        next_url = reverse("signup:company_join", args=(company.pk, token))
        params = {
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            previous_url=previous_url,
            next_url=next_url,
        )
        response = client.get(response.url, follow=True)
        response = accept_legal_terms(client, response)
        assertRedirects(response, reverse("welcoming_tour:index"))

        # Check `User` state.
        user = User.objects.get(email=pro_connect.oidc_userinfo["email"])
        assert company.has_admin(user)
        assert 1 == company.members.count()
        assert 1 == user.company_set.count()

    def test_user_invalid_company_id(self, client):
        user = random_pro_user_factory()
        client.force_login(user)

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
        user = random_pro_user_factory()
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
    def test_create_facilitator(self, client, mocker, mailoutbox, settings, snapshot):
        user = random_pro_user_factory()
        client.force_login(user)

        settings.API_INSEE_AUTH_URL = "https://insee.fake"
        settings.API_INSEE_SIRENE_URL = "https://entreprise.fake"
        settings.API_INSEE_CLIENT_ID = "foo"
        settings.API_INSEE_CLIENT_SECRET = "bar"
        mock_call_ban_geocoding_api = mocker.patch(
            "itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK
        )
        respx.post(f"{settings.API_INSEE_AUTH_URL}/token").mock(
            return_value=httpx.Response(200, json=INSEE_API_RESULT_MOCK)
        )

        FAKE_SIRET = "26570134200148"  # matches the one from ETABLISSEMENT_API_RESULT_MOCK for consistency

        url = reverse("signup:facilitator_search")
        post_data = {
            "siret": FAKE_SIRET,
        }

        # Mocks an invalid answer from the server
        respx.get(f"{settings.API_INSEE_SIRENE_URL}/siret/{FAKE_SIRET}").mock(
            return_value=httpx.Response(404, json={})
        )
        response = client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_not_called()
        assertContains(response, f"SIRET « {FAKE_SIRET} » non reconnu.")

        # Mock a valid answer from the server
        respx.get(f"{settings.API_INSEE_SIRENE_URL}/siret/{FAKE_SIRET}").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )
        response = client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_called_once()
        assertRedirects(response, reverse("signup:facilitator_join"), fetch_redirect_response=False)

        response = client.get(response.url)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot

        company = Company.objects.get(siret=FAKE_SIRET)
        assert company.has_admin(user)
        assert 1 == company.members.count()
        assert company.is_searchable is False

        # No sent email.
        assert len(mailoutbox) == 0

    def test_facilitator_base_signup_process(self, client):
        user = random_pro_user_factory()
        client.force_login(user)

        url = reverse("signup:company_select")
        response = client.get(url, {"siren": "111111111"})  # not existing SIREN
        assertContains(response, global_constants.ITOU_HELP_CENTER_URL)
        assertContains(response, get_tally_form_url("wA799W"))
        assertContains(response, reverse("signup:facilitator_search"))

    def test_company_select_does_not_die_under_requests(self, client, snapshot):
        user = random_pro_user_factory()
        client.force_login(user)

        companies = (
            CompanyFactory(siret="40219166200001", with_membership=True),
            CompanyFactory(siret="40219166200002", with_membership=True),
            CompanyFactory(siret="40219166200003", with_membership=True),
            CompanyFactory(siret="40219166200004", with_membership=True),
            CompanyFactory(siret="40219166200005", kind=CompanyKind.EI, with_membership=True),
            CompanyFactory(siret="40219166200005", kind=CompanyKind.AI, with_membership=True),
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

    def test_ignores_inactive_members(self, client):
        user = random_pro_user_factory()
        client.force_login(user)
        company = CompanyFactory(siret="40219166200001", with_jobs=True)
        membership_1 = CompanyMembershipFactory(company=company, is_active=False, user__is_active=True)
        membership_2 = CompanyMembershipFactory(company=company, is_active=True, user__is_active=False)
        response = client.get(reverse("signup:company_select"), {"siren": "402191662"})
        assertNotContains(response, self.to_join_msg(membership_1.user))
        assertNotContains(response, self.to_join_msg(membership_2.user))

    def test_admin_users_appears_first(self, client):
        user = random_pro_user_factory()
        client.force_login(user)
        company = CompanyFactory(siret="40219166200001")
        membership_1 = CompanyMembershipFactory(company=company, is_admin=False)
        response = client.get(reverse("signup:company_select"), {"siren": company.siret[:9]})
        assertContains(response, self.to_join_msg(membership_1.user))
        membership_2 = CompanyMembershipFactory(company=company, is_admin=True)
        assert company.memberships.count() == 2
        response = client.get(reverse("signup:company_select"), {"siren": company.siret[:9]})
        assertNotContains(response, self.to_join_msg(membership_1.user))
        assertContains(response, self.to_join_msg(membership_2.user))

    def test_with_next_param(self, client):
        user = random_pro_user_factory()
        client.force_login(user)

        next_url = reverse("dashboard:index")
        url = add_url_params(reverse("signup:company_select"), {"next": next_url})
        response = client.get(url)
        assertNotContains(response, "Votre formulaire contient une erreur")

        company = CompanyFactory(kind=CompanyKind.ETTI)
        post_data = {"siaes": company.pk}
        url = add_url_params(url, {"siren": company.siret[:9]})
        response = client.post(url, data=post_data)
        assertRedirects(response, next_url, fetch_redirect_response=False)

    @pytest.mark.parametrize("with_membership", [True, False])
    def test_cannot_join_ea_eatt(self, client, with_membership):
        user = random_pro_user_factory()
        client.force_login(user)

        CompanyFactory(
            siret="40219166200001",
            with_membership=with_membership,
            kind=random.choice([CompanyKind.EA, CompanyKind.EATT]),
        )
        response = client.get(reverse("signup:company_select"), {"siren": "402191662"})
        assertContains(response, "Aucun résultat pour 402191662")


def test_non_pro_cant_join_a_company(client):
    company = CompanyFactory(kind=CompanyKind.ETTI)
    assert company.members.count() == 0

    user = JobSeekerFactory()
    client.force_login(user)

    # Skip login process and jump to joining the company.
    token = company.get_token()
    url = reverse("signup:company_join", args=(company.pk, token))

    response = client.get(url, follow=True)
    assertMessages(
        response,
        [
            messages.Message(
                messages.ERROR,
                "Vous ne pouvez pas rejoindre une structure avec ce compte car vous n'êtes pas professionnel.",
            )
        ],
    )
    assertRedirects(response, reverse("search:employers_results"))

    # Check `User` state.
    assert not company.has_admin(user)
    assert company.members.count() == 0
