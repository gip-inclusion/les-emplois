import httpx
import pytest
import respx
from django.conf import settings
from django.contrib import auth, messages
from django.urls import reverse
from django.utils.html import escape
from django.utils.http import urlencode
from pytest_django.asserts import (
    assertContains,
    assertMessages,
    assertNotContains,
    assertRedirects,
    assertTemplateNotUsed,
    assertTemplateUsed,
)

from itou.openid_connect.pro_connect.constants import PRO_CONNECT_SESSION_KEY
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.enums import KIND_PRESCRIBER, UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.mocks.api_entreprise import ETABLISSEMENT_API_RESULT_MOCK, INSEE_API_RESULT_MOCK
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK
from itou.utils.urls import add_url_params
from itou.www.signup.forms import PrescriberChooseKindForm
from tests.prescribers.factories import (
    PrescriberOrganizationFactory,
    PrescriberOrganizationWithMembershipFactory,
    PrescriberPoleEmploiFactory,
)
from tests.users.factories import EmployerFactory, PrescriberFactory
from tests.utils.test import ItouClient


@pytest.fixture(autouse=True)
def setup_api_insee(settings):
    settings.API_INSEE_BASE_URL = "https://insee.fake"
    settings.API_INSEE_SIRENE_BASE_URL = "https://entreprise.fake"
    settings.API_INSEE_CONSUMER_KEY = "foo"
    settings.API_INSEE_CONSUMER_SECRET = "bar"


class TestPrescriberSignup:
    def setup_method(self):
        respx.post(f"{settings.API_INSEE_BASE_URL}/token").mock(
            return_value=httpx.Response(200, json=INSEE_API_RESULT_MOCK)
        )
        respx.get(f"{settings.API_INSEE_SIRENE_BASE_URL}/siret/26570134200148").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )

    def test_choose_user_kind(self, client):
        url = reverse("signup:choose_user_kind")
        response = client.get(url)
        assertContains(response, "Prescripteur / Orienteur")

        response = client.post(url, data={"kind": UserKind.PRESCRIBER})
        assertRedirects(response, reverse("signup:prescriber_check_already_exists"))

    @respx.mock
    def test_create_user_prescriber_member_of_france_travail(self, client, mailoutbox, pro_connect):
        organization = PrescriberPoleEmploiFactory()

        # Go through each step to ensure session data is recorded properly.
        # Step 1: the user works for PE follows PE link
        url = reverse("signup:prescriber_check_already_exists")
        response = client.get(url)
        safir_step_url = reverse("signup:prescriber_pole_emploi_safir_code")
        assertContains(response, safir_step_url)

        # Step 2: find PE organization by SAFIR code.
        response = client.get(url)
        post_data = {"safir_code": organization.code_safir_pole_emploi}
        response = client.post(safir_step_url, data=post_data)

        # Step 3: check email
        url = reverse("signup:prescriber_check_pe_email")
        assertRedirects(response, url)
        post_data = {"email": "athos@lestroismousquetaires.com"}
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors.get("email")

        email = f"athos{global_constants.FRANCE_TRAVAIL_EMAIL_SUFFIX}"
        post_data = {"email": email}
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("signup:prescriber_pole_emploi_user"))
        session_data = client.session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
        assert email == session_data.get("email")

        response = client.get(response.url)
        pro_connect.assertContainsButton(response)

        # Check ProConnect will redirect to the correct url
        previous_url = reverse("signup:prescriber_pole_emploi_user")
        next_url = reverse("signup:prescriber_join_org")
        params = {
            "user_email": email,
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        # Connect with ProConnect but no safir code is returned
        response = pro_connect.mock_oauth_dance(
            client,
            KIND_PRESCRIBER,
            user_email=email,
            channel="pole_emploi",
            user_info_email=email,
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = client.get(response.url, follow=True)
        assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Organization
        assert client.session.get(global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY) == organization.pk
        response = client.get(reverse("dashboard:index"))
        assertContains(response, f"Code SAFIR {organization.code_safir_pole_emploi}")

        user = User.objects.get(email=email)
        assert user.kind == UserKind.PRESCRIBER

        # Emails are not checked in Django anymore.
        assert not user.emailaddress_set.exists()

        # Check organization.
        assert organization.is_authorized
        assert organization.authorization_status == PrescriberAuthorizationStatus.VALIDATED

        # Check membership.
        assert 1 == user.prescriberorganization_set.count()
        assert user.prescribermembership_set.count() == 1
        assert user.prescribermembership_set.get().organization_id == organization.pk
        assert user.company_set.count() == 0

        [email] = mailoutbox
        assert email.subject == "[DEV] Votre rôle d’administrateur"

    @respx.mock
    def test_create_user_prescriber_with_authorized_org_returns_on_other_browser(
        self, client, mocker, mailoutbox, pro_connect
    ):
        mock_call_ban_geocoding_api = mocker.patch(
            "itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK
        )
        siret = "26570134200148"

        # Step 1: search organizations with SIRET
        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret,
            "department": "67",
        }
        response = client.post(url, data=post_data)

        # Step 2: ask the user to choose the organization he's working for in a pre-existing list.
        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret})
        assertRedirects(response, url)
        post_data = {
            "kind": PrescriberOrganizationKind.CAP_EMPLOI.value,
        }
        response = client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_called_once()

        # Step 3: Inclusion Connect button
        url = reverse("signup:prescriber_user")
        assertRedirects(response, url)
        response = client.get(url)
        pro_connect.assertContainsButton(response)

        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_user")
        next_url = reverse("signup:prescriber_join_org")
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        other_client = ItouClient()
        response = pro_connect.mock_oauth_dance(
            client,
            KIND_PRESCRIBER,
            previous_url=previous_url,
            next_url=next_url,
            other_client=other_client,
        )
        # Follow the redirection.
        response = other_client.get(response.url, follow=True)
        assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Check `User` state.
        user = User.objects.get(email=pro_connect.oidc_userinfo["email"])
        assert user.kind == UserKind.PRESCRIBER

        # Emails are not checked in Django anymore.
        assert not user.emailaddress_set.exists()

        # Check organization.
        org = PrescriberOrganization.objects.get(siret=siret)
        assert not org.is_authorized
        assert org.authorization_status == PrescriberAuthorizationStatus.NOT_SET

        # Check membership.
        assert 1 == user.prescriberorganization_set.count()
        assert user.prescribermembership_set.count() == 1
        membership = user.prescribermembership_set.get(organization=org)
        assert membership.is_admin

        # Check email has been sent to support (validation/refusal of authorisation needed).
        [authorization_email, administrator_email] = mailoutbox
        assert "Vérification de l'habilitation d'une nouvelle organisation" in authorization_email.subject
        assert administrator_email.subject == "[DEV] Votre rôle d’administrateur"

    @respx.mock
    def test_create_user_prescriber_with_authorized_org_of_known_kind(self, client, mocker, mailoutbox, pro_connect):
        """
        Test the creation of a user of type prescriber with an authorized organization of *known* kind.
        """
        mock_call_ban_geocoding_api = mocker.patch(
            "itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK
        )
        siret = "26570134200148"

        # Step 1: search organizations with SIRET
        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret,
            "department": "67",
        }
        response = client.post(url, data=post_data)

        # Step 2: ask the user to choose the organization he's working for in a pre-existing list.
        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret})
        assertRedirects(response, url)
        post_data = {
            "kind": PrescriberOrganizationKind.CAP_EMPLOI.value,
        }
        response = client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_called_once()

        # Step 3: Inclusion Connect button
        url = reverse("signup:prescriber_user")
        assertRedirects(response, url)
        response = client.get(url)
        pro_connect.assertContainsButton(response)

        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_user")
        next_url = reverse("signup:prescriber_join_org")
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            KIND_PRESCRIBER,
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = client.get(response.url, follow=True)
        assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Check `User` state.
        user = User.objects.get(email=pro_connect.oidc_userinfo["email"])
        assert user.kind == UserKind.PRESCRIBER

        # Emails are not checked in Django anymore.
        assert not user.emailaddress_set.exists()

        # Check organization.
        org = PrescriberOrganization.objects.get(siret=siret)
        assert not org.is_authorized
        assert org.authorization_status == PrescriberAuthorizationStatus.NOT_SET

        # Check membership.
        assert 1 == user.prescriberorganization_set.count()
        assert user.prescribermembership_set.count() == 1
        membership = user.prescribermembership_set.get(organization=org)
        assert membership.is_admin

        # Check email has been sent to support (validation/refusal of authorisation needed).
        [authorization_email, administrator_email] = mailoutbox
        assert "Vérification de l'habilitation d'une nouvelle organisation" in authorization_email.subject
        body_lines = authorization_email.body.splitlines()
        assert "- Nom : CENTRE COMMUNAL D'ACTION SOCIALE" in body_lines
        assert f"- ID : {org.pk}" in body_lines
        assert "- Type sélectionné par l’utilisateur : Cap emploi" in body_lines
        assert administrator_email.subject == "[DEV] Votre rôle d’administrateur"

    @respx.mock
    def test_create_user_prescriber_with_authorized_org_of_unknown_kind(self, client, mocker, mailoutbox, pro_connect):
        """
        Test the creation of a user of type prescriber with an authorized organization of *unknown* kind.
        """
        mock_call_ban_geocoding_api = mocker.patch(
            "itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK
        )
        siret = "26570134200148"

        # Step 1: search organizations with SIRET
        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret,
            "department": "67",
        }
        response = client.post(url, data=post_data)

        # Step 2: set 'other' organization.
        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret})
        assertRedirects(response, url)
        post_data = {
            "kind": PrescriberOrganizationKind.OTHER.value,
        }
        response = client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_called_once()

        # Step 3: ask the user his kind of prescriber.
        url = reverse("signup:prescriber_choose_kind")
        assertRedirects(response, url)
        post_data = {
            "kind": PrescriberChooseKindForm.KIND_AUTHORIZED_ORG,
        }
        response = client.post(url, data=post_data)

        # Step 4: ask the user to confirm the "authorized" character of his organization.
        url = reverse("signup:prescriber_confirm_authorization")
        assertRedirects(response, url)
        post_data = {
            "confirm_authorization": 1,
        }
        response = client.post(url, data=post_data)

        # Step 5: Inclusion Connect button
        url = reverse("signup:prescriber_user")
        assertRedirects(response, url)
        response = client.get(url)
        pro_connect.assertContainsButton(response)

        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_user")
        next_url = reverse("signup:prescriber_join_org")
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        previous_url = reverse("signup:prescriber_user")
        response = pro_connect.mock_oauth_dance(
            client,
            KIND_PRESCRIBER,
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = client.get(response.url, follow=True)
        assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Check `User` state.
        user = User.objects.get(email=pro_connect.oidc_userinfo["email"])
        assert user.kind == UserKind.PRESCRIBER

        # Emails are not checked in Django anymore.
        assert not user.emailaddress_set.exists()

        # Check organization.
        org = PrescriberOrganization.objects.get(siret=siret)
        assert not org.is_authorized
        assert org.authorization_status == PrescriberAuthorizationStatus.NOT_SET

        # Check membership.
        assert 1 == user.prescriberorganization_set.count()
        assert user.prescribermembership_set.count() == 1
        membership = user.prescribermembership_set.get(organization=org)
        assert membership.is_admin

        # Check email has been sent to support (validation/refusal of authorisation needed).
        [authorization_email, administrator_email] = mailoutbox
        assert "Vérification de l'habilitation d'une nouvelle organisation" in authorization_email.subject
        assert administrator_email.subject == "[DEV] Votre rôle d’administrateur"

    @respx.mock
    def test_create_user_prescriber_with_unauthorized_org(self, client, mocker, mailoutbox, pro_connect):
        """
        Test the creation of a user of type prescriber with an unauthorized organization.
        """
        mock_call_ban_geocoding_api = mocker.patch(
            "itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK
        )
        siret = "26570134200148"

        # Step 1: search organizations with SIRET
        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret,
            "department": "67",
        }
        response = client.post(url, data=post_data)

        # Step 2: select kind of organization.
        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret})
        assertRedirects(response, url)
        post_data = {
            "kind": PrescriberOrganizationKind.OTHER.value,
        }
        response = client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_called_once()

        # Step 3: select the kind of prescriber 'UNAUTHORIZED'.
        url = reverse("signup:prescriber_choose_kind")
        assertRedirects(response, url)
        post_data = {
            "kind": PrescriberChooseKindForm.KIND_UNAUTHORIZED_ORG,
        }
        response = client.post(url, data=post_data)

        # Step 4: Inclusion Connect button
        url = reverse("signup:prescriber_user")
        assertRedirects(response, url)
        response = client.get(url)
        pro_connect.assertContainsButton(response)

        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_user")
        next_url = reverse("signup:prescriber_join_org")
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            KIND_PRESCRIBER,
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = client.get(response.url, follow=True)
        assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Check `User` state.
        user = User.objects.get(email=pro_connect.oidc_userinfo["email"])
        assert user.kind == UserKind.PRESCRIBER

        # Emails are not checked in Django anymore.
        assert not user.emailaddress_set.exists()

        # Check organization.
        org = PrescriberOrganization.objects.get(siret=siret)
        assert not org.is_authorized
        assert org.authorization_status == PrescriberAuthorizationStatus.NOT_REQUIRED

        # Check membership.
        assert 1 == user.prescriberorganization_set.count()
        assert user.prescribermembership_set.count() == 1
        membership = user.prescribermembership_set.get(organization=org)
        assert membership.is_admin

        [email] = mailoutbox
        assert email.subject == "[DEV] Votre rôle d’administrateur"

    def test_create_user_prescriber_with_existing_siren_other_department(self, client):
        """
        Test the creation of a user of type prescriber with existing SIREN but in an other department
        """

        siret1 = "26570134200056"
        siret2 = "26570134200148"

        # PrescriberOrganizationWithMembershipFactory.
        PrescriberOrganizationWithMembershipFactory(
            siret=siret1, kind=PrescriberOrganizationKind.SPIP, department="01"
        )

        # Step 1: search organizations with SIRET
        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret2,
            "department": "67",
        }
        response = client.post(url, data=post_data)

        # Step 2: redirect to kind of organization selection.
        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret2})
        assertRedirects(response, url)

    def test_create_user_prescriber_with_existing_siren_same_department(self, client):
        """
        Test the creation of a user of type prescriber with existing SIREN in a same department
        """
        siret1 = "26570134200056"
        siret2 = "26570134200148"

        existing_org_with_siret = PrescriberOrganizationWithMembershipFactory(
            siret=siret1, kind=PrescriberOrganizationKind.SPIP, department="67"
        )

        # Search organizations with SIRET
        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret2,
            "department": "67",
        }
        response = client.post(url, data=post_data)
        assertContains(response, existing_org_with_siret.display_name)

        # Request for an invitation link.
        prescriber_membership = (
            PrescriberMembership.objects.filter(organization=existing_org_with_siret)
            .active()
            .select_related("user")
            .order_by("-is_admin", "joined_at")
            .first()
        )
        assertContains(
            response,
            reverse("signup:prescriber_request_invitation", kwargs={"membership_id": prescriber_membership.id}),
        )

        # New organization link.
        assertContains(response, reverse("signup:prescriber_choose_org"))

    def test_create_user_prescriber_with_existing_siren_without_member(self, client):
        """
        Test the creation of a user of type prescriber with existing organization does not have a member
        """

        siret1 = "26570134200056"
        siret2 = "26570134200148"

        PrescriberOrganizationFactory(siret=siret1, kind=PrescriberOrganizationKind.SPIP, department="67")

        # Search organizations with SIRET
        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret2,
            "department": "67",
        }
        response = client.post(url, data=post_data)

        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret2})
        assertRedirects(response, url)

    @respx.mock
    def test_create_user_prescriber_without_org(self, client, mailoutbox, pro_connect):
        """
        Test the creation of a user of type prescriber without organization.
        """
        # Step 1: the user clicks on "No organization" in search of organization
        # (SIREN and department).
        url = reverse("signup:prescriber_check_already_exists")
        response = client.get(url)

        # Step 2: Inclusion Connect button
        url = reverse("signup:prescriber_user")
        assertContains(response, url)
        response = client.get(url)
        pro_connect.assertContainsButton(response)

        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_user")
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            KIND_PRESCRIBER,
            previous_url=previous_url,
        )
        # Follow the redirection.
        response = client.get(response.url, follow=True)
        assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Check `User` state.
        user = User.objects.get(email=pro_connect.oidc_userinfo["email"])
        assert user.kind == UserKind.PRESCRIBER

        # Emails are not checked in Django anymore.
        assert not user.emailaddress_set.exists()

        # Check membership.
        assert 0 == user.prescriberorganization_set.count()

        # No email has been sent.
        assert len(mailoutbox) == 0

    @respx.mock
    def test_create_user_prescriber_with_same_siret_and_different_kind(self, client, mocker, pro_connect):
        """
        A user can create a new prescriber organization with an existing SIRET number,
        provided that:
        - the kind of the new organization is different from the existing one
        - there is no duplicate of the (kind, siret) pair

        Example cases:
        - user can't create 2 PLIE with the same SIRET
        - user can create a PLIE and a ML with the same SIRET
        """
        mock_call_ban_geocoding_api = mocker.patch(
            "itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK
        )
        # Same SIRET as mock.
        siret = "26570134200148"
        respx.get(f"{settings.API_INSEE_SIRENE_BASE_URL}/siret/{siret}").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )
        existing_org_with_siret = PrescriberOrganizationFactory(siret=siret, kind=PrescriberOrganizationKind.ML)

        # Step 1: search organizations with SIRET
        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret,
            "department": "67",
        }
        response = client.post(url, data=post_data)
        assertContains(response, existing_org_with_siret.display_name)

        # Step 2: Select kind
        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret})
        post_data = {"kind": PrescriberOrganizationKind.PLIE.value}
        response = client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_called_once()

        # Step 3: Inclusion Connect button
        url = reverse("signup:prescriber_user")
        assertRedirects(response, url)
        response = client.get(url)
        pro_connect.assertContainsButton(response)

        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_user")
        next_url = reverse("signup:prescriber_join_org")
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            KIND_PRESCRIBER,
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = client.get(response.url, follow=True)
        assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Check new org is OK.
        same_siret_orgs = PrescriberOrganization.objects.filter(siret=siret).order_by("kind").all()
        assert 2 == len(same_siret_orgs)
        org1, org2 = same_siret_orgs
        assert PrescriberOrganizationKind.ML.value == org1.kind
        assert PrescriberOrganizationKind.PLIE.value == org2.kind

    @respx.mock
    def test_create_user_prescriber_with_same_siret_and_same_kind(self, client, mocker, pro_connect):
        """
        A user can't create a new prescriber organization with an existing SIRET number if:
        * the kind of the new organization is the same as an existing one
        * there is no duplicate of the (kind, siret) pair
        """
        mock_call_ban_geocoding_api = mocker.patch(
            "itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK
        )
        # Same SIRET as mock but with same expected kind.
        siret = "26570134200148"
        respx.get(f"{settings.API_INSEE_SIRENE_BASE_URL}/siret/{siret}").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )
        prescriber_organization = PrescriberOrganizationFactory(siret=siret, kind=PrescriberOrganizationKind.PLIE)

        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret,
            "department": "67",
        }
        response = client.post(url, data=post_data)

        assertContains(response, prescriber_organization.display_name)

        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret})
        post_data = {
            "kind": PrescriberOrganizationKind.PLIE.value,
        }
        response = client.post(url, data=post_data)
        assertContains(response, "utilise déjà ce type d'organisation avec le même SIRET")
        mock_call_ban_geocoding_api.assert_called_once()

    def test_form_to_request_for_an_invitation(self, client, mailoutbox):
        siret = "26570134200148"
        prescriber_org = PrescriberOrganizationWithMembershipFactory(siret=siret)
        prescriber_membership = prescriber_org.prescribermembership_set.first()

        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": prescriber_org.siret,
            "department": prescriber_org.department,
        }
        response = client.post(url, data=post_data)
        assertContains(response, prescriber_org.display_name)

        url = reverse("signup:prescriber_request_invitation", kwargs={"membership_id": prescriber_membership.id})
        response = client.get(url)
        assertContains(response, prescriber_org.display_name)

        response = client.post(url, data={"first_name": "Bertrand", "last_name": "Martin", "email": "beber"})
        assertContains(response, "Saisissez une adresse e-mail valide.")

        requestor = {"first_name": "Bertrand", "last_name": "Martin", "email": "bertand@wahoo.fr"}
        response = client.post(url, data=requestor)
        assert response.status_code == 302

        assert len(mailoutbox) == 1
        mail_subject = mailoutbox[0].subject
        assert f"Demande pour rejoindre {prescriber_org.display_name}" in mail_subject
        mail_body = mailoutbox[0].body
        assert prescriber_membership.user.get_full_name() in mail_body
        assert prescriber_membership.organization.display_name in mail_body
        invitation_url = f"{reverse('invitations_views:invite_prescriber_with_org')}?{urlencode(requestor)}"
        assert invitation_url in mail_body

    @respx.mock
    def test_prescriber_already_exists__simple_signup(self, client, pro_connect):
        """
        He does not want to join an organization, only create an account.
        He likely forgot he had an account.
        He will be logged in instead as if he just used the login through IC button
        """
        #### User is a prescriber. Update it and connect. ####
        PrescriberFactory(email=pro_connect.oidc_userinfo["email"], username=pro_connect.oidc_userinfo["sub"])
        client.get(reverse("signup:prescriber_check_already_exists"))

        # Step 2: register as a simple prescriber (orienteur).
        response = client.get(reverse("signup:prescriber_user"))
        pro_connect.assertContainsButton(response)

        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_user")
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        # Connect with Inclusion Connect.
        response = pro_connect.mock_oauth_dance(
            client,
            KIND_PRESCRIBER,
            previous_url=previous_url,
        )
        # Follow the redirection.
        response = client.get(response.url, follow=True)
        assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        user = User.objects.get(email=pro_connect.oidc_userinfo["email"])
        assert user.has_sso_provider

    @respx.mock
    def test_prescriber_already_exists__create_organization(self, client, pro_connect):
        """
        User is already a prescriber.
        We should update his account and make him join this new organization.
        """
        org = PrescriberOrganizationFactory.build(kind=PrescriberOrganizationKind.OTHER)
        user = PrescriberFactory(email=pro_connect.oidc_userinfo["email"], username=pro_connect.oidc_userinfo["sub"])

        client.get(reverse("signup:prescriber_check_already_exists"))

        session_signup_data = client.session.get(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
        # Jump over the last step to avoid double-testing each one
        # as they are already tested on prescriber's signup views.
        # Prescriber's signup process heavily relies on session data.
        # Override only what's needed for our test.
        # PrescriberOrganizationFactoy does not contain any address field
        # so we can't use it.
        prescriber_org_data = {
            "siret": org.siret,
            "is_head_office": True,
            "name": org.name,
            "address_line_1": "17 RUE JEAN DE LA FONTAINE",
            "address_line_2": "",
            "post_code": "13150",
            "city": "TARASCON",
            "department": "13",
            "longitude": 4.660572,
            "latitude": 43.805661,
            "geocoding_score": 0.8178357293868921,
        }
        session_signup_data = session_signup_data | {
            "authorization_status": "NOT_SET",
            "kind": org.kind,
            "prescriber_org_data": prescriber_org_data,
        }

        client_session = client.session
        client_session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = session_signup_data
        client_session.save()
        signup_url = reverse("signup:prescriber_user")

        response = client.get(signup_url)
        pro_connect.assertContainsButton(response)

        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_user")
        next_url = reverse("signup:prescriber_join_org")
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        # Connect with Inclusion Connect.
        response = pro_connect.mock_oauth_dance(
            client,
            KIND_PRESCRIBER,
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = client.get(response.url, follow=True)
        assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Check organization
        org = PrescriberOrganization.objects.get(siret=org.siret)
        assert not org.is_authorized
        assert org.authorization_status == PrescriberAuthorizationStatus.NOT_SET

        # Check membership.
        assert user.prescribermembership_set.count() == 1
        membership = user.prescribermembership_set.get(organization=org)
        assert membership.is_admin

    def test_hidden_organization_kinds(self, client, mocker):
        """
        HIDDEN_PRESCRIBER_KINDS should not be displayed or chosen in the form
        """
        mocker.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)

        siret = "26570134200148"

        # Step 1: search organizations with SIRET
        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret,
            "department": "67",
        }
        response = client.post(url, data=post_data)

        # Step 2: ask the user to choose the organization he's working for in a pre-existing list.
        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret})
        assertRedirects(response, url)

        response = client.get(url)
        assertContains(response, PrescriberOrganizationKind.CAP_EMPLOI.value)
        assertNotContains(response, PrescriberOrganizationKind.OHPD.value)
        assertNotContains(response, PrescriberOrganizationKind.OCASF.value)
        # We cannot check for Orienteur since it's also in the template in other places
        # but we can check it's refused in the form
        post_data = {
            "kind": PrescriberOrganizationKind.ORIENTEUR.value,
        }
        response = client.post(url, data=post_data)
        assert "kind" in response.context["form"].errors


class TestProConnectPrescribersViewsExceptions:
    """
    Prescribers' signup and login exceptions: user already exists, ...
    """

    @respx.mock
    def test_organization_creation_error(self, client, pro_connect):
        """
        The organization creation didn't work.
        The user is still created and can try again.
        """
        org = PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.OTHER)
        user = PrescriberFactory(email=pro_connect.oidc_userinfo["email"], username=pro_connect.oidc_userinfo["sub"])

        client.get(reverse("signup:prescriber_check_already_exists"))

        session_signup_data = client.session.get(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
        # Jump over the last step to avoid double-testing each one
        # as they are already tested on prescriber's signup views.
        # Prescriber's signup process heavily relies on session data.
        # Override only what's needed for our test.
        # PrescriberOrganizationFactoy does not contain any address field
        # so we can't use it.
        prescriber_org_data = {
            "siret": org.siret,
            "is_head_office": True,
            "name": org.name,
            "address_line_1": "17 RUE JEAN DE LA FONTAINE",
            "address_line_2": "",
            "post_code": "13150",
            "city": "TARASCON",
            "department": "13",
            "longitude": 4.660572,
            "latitude": 43.805661,
            "geocoding_score": 0.8178357293868921,
        }
        # Try creating an organization with same siret and same kind
        # (it won't work because of the psql uniqueness constraint).
        session_signup_data = session_signup_data | {
            "authorization_status": "NOT_SET",
            "kind": org.kind,
            "prescriber_org_data": prescriber_org_data,
        }

        client_session = client.session
        client_session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = session_signup_data
        client_session.save()
        signup_url = reverse("signup:prescriber_user")

        response = client.get(signup_url)
        pro_connect.assertContainsButton(response)

        # Connect with Inclusion Connect.
        previous_url = reverse("signup:prescriber_user")
        next_url = reverse("signup:prescriber_join_org")
        response = pro_connect.mock_oauth_dance(
            client,
            KIND_PRESCRIBER,
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = client.get(response.url)
        assertRedirects(
            response,
            add_url_params(pro_connect.logout_url, {"token": 123456}),
            fetch_redirect_response=False,
        )

        # The user should be logged out and redirected to the home page.
        assert not client.session.get(PRO_CONNECT_SESSION_KEY)
        assert not auth.get_user(client).is_authenticated

        # Check user was created but did not join an organisation
        user = User.objects.get(email=pro_connect.oidc_userinfo["email"])
        assert not user.prescriberorganization_set.exists()

    @respx.mock
    def test_non_prescriber_cant_join_organisation(self, client, pro_connect):
        """
        The organization creation didn't work.
        The user is still created and can try again.
        """
        org = PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.OTHER)
        EmployerFactory(
            email=pro_connect.oidc_userinfo["email"], username=pro_connect.oidc_userinfo["sub"], with_company=True
        )

        response = client.get(reverse("signup:prescriber_check_already_exists"))
        assert response.status_code == 200

        session_signup_data = client.session.get(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
        # Jump over the last step to avoid double-testing each one
        # as they are already tested on prescriber's signup views.
        # Prescriber's signup process heavily relies on session data.
        # Override only what's needed for our test.
        # PrescriberOrganizationFactoy does not contain any address field
        # so we can't use it.
        prescriber_org_data = {
            "siret": org.siret,
            "is_head_office": True,
            "name": org.name,
            "address_line_1": "17 RUE JEAN DE LA FONTAINE",
            "address_line_2": "",
            "post_code": "13150",
            "city": "TARASCON",
            "department": "13",
            "longitude": 4.660572,
            "latitude": 43.805661,
            "geocoding_score": 0.8178357293868921,
        }
        # Try creating an organization with same siret and same kind
        # (it won't work because of the psql uniqueness constraint).
        session_signup_data = session_signup_data | {
            "authorization_status": "NOT_SET",
            "kind": org.kind,
            "prescriber_org_data": prescriber_org_data,
        }

        client_session = client.session
        client_session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = session_signup_data
        client_session.save()
        signup_url = reverse("signup:prescriber_user")

        response = client.get(signup_url)
        pro_connect.assertContainsButton(response)

        # Connect with Inclusion Connect.
        previous_url = signup_url
        next_url = reverse("signup:prescriber_join_org")
        response = pro_connect.mock_oauth_dance(
            client,
            KIND_PRESCRIBER,
            previous_url=previous_url,
            next_url=next_url,
            register=False,
        )
        # Follow the redirection.
        response = client.get(response.url, follow=True)
        assertTemplateNotUsed(response, "welcoming_tour/prescriber.html")

        # The user should be redirected to home page with a warning, the session isn't flushed
        assert client.session.get(pro_connect.session_key)
        assert auth.get_user(client).is_authenticated
        assertRedirects(response, reverse("search:employers_home"))
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Vous ne pouvez pas rejoindre une organisation avec ce compte car vous n'êtes pas prescripteur.",
                )
            ],
        )

    @respx.mock
    def test_employer_already_exists(self, client, pro_connect):
        """
        User is already a member of an SIAE.
        Raise an exception.
        """
        org = PrescriberOrganizationFactory.build(kind=PrescriberOrganizationKind.OTHER)
        user = EmployerFactory(email=pro_connect.oidc_userinfo["email"], username=pro_connect.oidc_userinfo["sub"])
        client.get(reverse("signup:prescriber_check_already_exists"))

        session_signup_data = client.session.get(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
        # Jump over the last step to avoid double-testing each one
        # as they are already tested on prescriber's signup views.
        # Prescriber's signup process heavily relies on session data.
        # Override only what's needed for our test.
        # PrescriberOrganizationFactoy does not contain any address field
        # so we can't use it.
        prescriber_org_data = {
            "siret": org.siret,
            "is_head_office": True,
            "name": org.name,
            "address_line_1": "17 RUE JEAN DE LA FONTAINE",
            "address_line_2": "",
            "post_code": "13150",
            "city": "TARASCON",
            "department": "13",
            "longitude": 4.660572,
            "latitude": 43.805661,
            "geocoding_score": 0.8178357293868921,
        }
        session_signup_data = session_signup_data | {
            "authorization_status": "NOT_SET",
            "kind": org.kind,
            "prescriber_org_data": prescriber_org_data,
        }

        client_session = client.session
        client_session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = session_signup_data
        client_session.save()
        signup_url = reverse("signup:prescriber_user")

        response = client.get(signup_url)
        pro_connect.assertContainsButton(response)

        # Connect with Inclusion Connect.
        previous_url = reverse("signup:prescriber_user")
        next_url = reverse("signup:prescriber_join_org")
        response = pro_connect.mock_oauth_dance(
            client,
            KIND_PRESCRIBER,
            previous_url=previous_url,
            next_url=next_url,
            expected_redirect_url=add_url_params(pro_connect.logout_url, {"redirect_url": previous_url}),
        )

        # IC logout redirects to previous_url
        response = client.get(previous_url)
        # Show an error and don't create an organization.

        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Un compte employeur existe déjà avec cette adresse e-mail. Vous devez créer un compte "
                    f"{pro_connect.identity_provider.label} avec une autre adresse e-mail pour devenir prescripteur "
                    "sur la plateforme. "
                    f"Besoin d'aide ? <a href='{global_constants.ITOU_HELP_CENTER_URL}/requests/new' "
                    "target='_blank'>Contactez-nous</a>.",
                )
            ],
        )

        user = User.objects.get(email=pro_connect.oidc_userinfo["email"])
        assert user.first_name != pro_connect.oidc_userinfo["given_name"]
        organization_exists = PrescriberOrganization.objects.filter(siret=org.siret).exists()
        assert not organization_exists
        assert not user.prescriberorganization_set.exists()

    @respx.mock
    def test_prescriber_signup__ft_organization_wrong_email(self, client, pro_connect):
        """
        A user creates a prescriber account on Itou with Inclusion Connect.
        He wants to join a Pôle emploi organization
        but his e-mail suffix is wrong. An error should be raised.
        """
        pe_org = PrescriberPoleEmploiFactory()
        pe_email = f"athos{global_constants.POLE_EMPLOI_EMAIL_SUFFIX}"

        # Go through each step to ensure session data is recorded properly.
        # Step 1: choose organization kind or go to the "no organization" page.
        client.get(reverse("signup:prescriber_check_already_exists"))

        # Step 2: find PE organization by SAFIR code.
        safir_step_url = reverse("signup:prescriber_pole_emploi_safir_code")
        response = client.get(safir_step_url)
        post_data = {"safir_code": pe_org.code_safir_pole_emploi}
        response = client.post(safir_step_url, data=post_data, follow=True)

        # Step 3: check email
        check_email_url = reverse("signup:prescriber_check_pe_email")
        post_data = {"email": pe_email}
        response = client.post(check_email_url, data=post_data, follow=True)
        pro_connect.assertContainsButton(response)

        # Connect with Inclusion Connect but, this time, don't use a PE email.
        previous_url = reverse("signup:prescriber_pole_emploi_user")
        next_url = reverse("signup:prescriber_join_org")
        wrong_email = "athos@touspourun.com"
        response = pro_connect.mock_oauth_dance(
            client,
            KIND_PRESCRIBER,
            user_email=pe_email,
            channel="pole_emploi",
            previous_url=previous_url,
            next_url=next_url,
            user_info_email=wrong_email,
            expected_redirect_url=add_url_params(pro_connect.logout_url, {"redirect_url": previous_url}),
        )

        # IC logout redirects to previous_url
        response = client.get(previous_url)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "L’adresse e-mail que vous avez utilisée pour vous connecter avec "
                    f"{pro_connect.identity_provider.label} (athos@touspourun.com) est différente de celle que vous "
                    "avez indiquée précédemment (athos@pole-emploi.fr).",
                )
            ],
        )

        # Organization
        assert not client.session.get(global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY)
        assert not User.objects.filter(email=pe_email).exists()

    def test_permission_denied_when_skiping_first_step(self, client, subtests):
        urls = [
            reverse("signup:prescriber_request_invitation", kwargs={"membership_id": 1}),
            reverse("signup:prescriber_choose_org"),
            reverse("signup:prescriber_choose_kind"),
            reverse("signup:prescriber_confirm_authorization"),
            reverse("signup:prescriber_pole_emploi_safir_code"),
            reverse("signup:prescriber_check_pe_email"),
            reverse("signup:prescriber_pole_emploi_user"),
            reverse("signup:prescriber_user"),
        ]
        for url in urls:
            with subtests.test(url=url):
                response = client.get(url)
                assert response.status_code == 403
        # This view requires to be logged in
        url = reverse("signup:prescriber_join_org")
        with subtests.test(url=url):
            client.force_login(PrescriberFactory())
            response = client.get(url)
            assert response.status_code == 403
