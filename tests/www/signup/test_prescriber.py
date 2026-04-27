import uuid

import httpx
import pytest
import respx
from django.conf import settings
from django.urls import reverse
from django.utils.html import escape
from django.utils.http import urlencode
from pytest_django.asserts import (
    assertContains,
    assertNotContains,
    assertQuerySetEqual,
    assertRedirects,
    assertTemplateUsed,
)

from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.enums import IdentityProvider
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.mocks.api_entreprise import ETABLISSEMENT_API_RESULT_MOCK, INSEE_API_RESULT_MOCK
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK
from itou.www.signup.forms import PrescriberChooseKindForm
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import random_pro_user_factory


@pytest.fixture(autouse=True)
def setup_api_insee(settings):
    settings.API_INSEE_AUTH_URL = "https://insee.fake"
    settings.API_INSEE_SIRENE_URL = "https://entreprise.fake"
    settings.API_INSEE_CLIENT_ID = "foo"
    settings.API_INSEE_CLIENT_SECRET = "bar"


class TestPrescriberSignup:
    def setup_method(self):
        respx.post(f"{settings.API_INSEE_AUTH_URL}/token").mock(
            return_value=httpx.Response(200, json=INSEE_API_RESULT_MOCK)
        )
        respx.get(f"{settings.API_INSEE_SIRENE_URL}/siret/26570134200148").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )

    @pytest.mark.parametrize("already_has_membership", [True, False])
    def test_professional_is_member_of_france_travail(self, client, mailoutbox, already_has_membership):
        email = f"athos{global_constants.FRANCE_TRAVAIL_EMAIL_SUFFIX}"
        user = random_pro_user_factory(email=email, identity_provider=IdentityProvider.PRO_CONNECT)
        client.force_login(user)

        if already_has_membership:
            # create a previous org to ensure the user is switched to the new org
            old_org = PrescriberMembershipFactory(user=user, organization__france_travail=True).organization
        organization = PrescriberOrganizationFactory(france_travail=True)

        # Go through each step to ensure session data is recorded properly.
        # Step 1: the user works for PE follows PE link
        url = reverse("signup:prescriber_check_already_exists")
        response = client.get(url)
        safir_step_url = reverse("signup:prescriber_search_ft_org")
        assertContains(response, safir_step_url)
        if already_has_membership:
            assert (
                client.session.get(global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY)
                == old_org.organization_switch_key
            )

        # Step 2: find PE organization by SAFIR code.
        response = client.get(url)
        post_data = {"safir_code": organization.code_safir_pole_emploi}
        response = client.post(safir_step_url, data=post_data)

        join_step_url = reverse("signup:prescriber_join_ft_org", kwargs={"uuid": organization.uid})
        assertRedirects(response, join_step_url)

        # Step3 3: join the organization
        response = client.post(join_step_url, data=post_data)
        assertRedirects(response, reverse("welcoming_tour:index"))

        # Organization
        assert (
            client.session.get(global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY)
            == organization.organization_switch_key
        )
        response = client.get(reverse("dashboard:index"))
        assertContains(response, f"Code SAFIR {organization.code_safir_pole_emploi}")

        user = User.objects.get(email=email)

        # Emails are not checked in Django anymore.
        assert not user.emailaddress_set.exists()

        # Check organization.
        assert organization.is_authorized
        assert organization.authorization_status == PrescriberAuthorizationStatus.VALIDATED

        # Check membership.
        assertQuerySetEqual(
            user.prescribermembership_set.all(),
            [old_org, organization] if already_has_membership else [organization],
            transform=lambda m: m.organization,
            ordered=False,
        )
        assert user.company_set.count() == 0

        [email] = mailoutbox
        assert email.subject == "[TEST] Votre rôle d’administrateur"

    @respx.mock
    def test_join_an_authorized_org_of_known_kind(self, client, mocker, mailoutbox):
        """
        Test joining an authorized organization of *known* kind.
        """
        user = random_pro_user_factory(identity_provider=IdentityProvider.PRO_CONNECT)
        client.force_login(user)

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
        assertRedirects(response, reverse("signup:prescriber_join_org"), fetch_redirect_response=False)

        # Step 3: Follow the redirections and join the org
        response = client.get(response.url, follow=True)
        assertTemplateUsed(response, "welcoming_tour/prescriber.html")

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
        assert administrator_email.subject == "[TEST] Votre rôle d’administrateur"

    @respx.mock
    def test_join_an_authorized_org_of_unknown_kind(self, client, mocker, mailoutbox):
        """
        Test joining an authorized organization of *unknown* kind.
        """
        user = random_pro_user_factory(identity_provider=IdentityProvider.PRO_CONNECT)
        client.force_login(user)

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
        assertRedirects(response, reverse("signup:prescriber_join_org"), fetch_redirect_response=False)

        # Step 5: Follow the redirections and join the org
        response = client.get(response.url, follow=True)
        assertTemplateUsed(response, "welcoming_tour/prescriber.html")

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
        assert administrator_email.subject == "[TEST] Votre rôle d’administrateur"

    @respx.mock
    def test_join_an_unauthorized_org(self, client, mocker, mailoutbox):
        """
        Test joining an unauthorized organization.
        """
        user = random_pro_user_factory(identity_provider=IdentityProvider.PRO_CONNECT)
        client.force_login(user)

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
        assertRedirects(response, reverse("signup:prescriber_join_org"), fetch_redirect_response=False)

        # Step 4: Follow the redirections and join the org
        response = client.get(response.url, follow=True)
        assertTemplateUsed(response, "welcoming_tour/prescriber.html")

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
        assert email.subject == "[TEST] Votre rôle d’administrateur"

    def test_check_org_with_existing_siren_other_department(self, client):
        """
        Test checking for existing org with existing SIREN but in an other department
        """
        user = random_pro_user_factory()
        client.force_login(user)

        siret1 = "26570134200056"
        siret2 = "26570134200148"

        PrescriberOrganizationFactory(
            siret=siret1, kind=PrescriberOrganizationKind.SPIP, department="01", with_membership=True
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

    def test_check_org_with_existing_siren_same_department(self, client):
        """
        Test checking for existing org with existing SIREN but in the same department
        """
        user = random_pro_user_factory()
        client.force_login(user)

        siret1 = "26570134200056"
        siret2 = "26570134200148"

        existing_org_with_siret = PrescriberOrganizationFactory(
            siret=siret1, kind=PrescriberOrganizationKind.SPIP, department="67", with_membership=True
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

    def test_check_org_without_member(self, client):
        """
        Test check for existing org if the organization does not have a member
        """
        user = random_pro_user_factory()
        client.force_login(user)

        siret = "26570134200148"

        # Search organizations with SIRET
        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret,
            "department": "67",
        }
        response = client.post(url, data=post_data)

        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret})
        assertRedirects(response, url)

    @respx.mock
    def test_join_new_organization_with_same_siret_and_different_kind(self, client, mocker):
        """
        A user can create a new prescriber organization with an existing SIRET number,
        provided that:
        - the kind of the new organization is different from the existing one
        - there is no duplicate of the (kind, siret) pair

        Example cases:
        - user can't create 2 PLIE with the same SIRET
        - user can create a PLIE and a ML with the same SIRET
        """
        user = random_pro_user_factory(identity_provider=IdentityProvider.PRO_CONNECT)
        client.force_login(user)

        mock_call_ban_geocoding_api = mocker.patch(
            "itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK
        )
        # Same SIRET as mock.
        siret = "26570134200148"
        respx.get(f"{settings.API_INSEE_SIRENE_URL}/siret/{siret}").mock(
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
        assertRedirects(response, reverse("signup:prescriber_join_org"), fetch_redirect_response=False)

        # Step 4: Follow the redirections and join the org
        response = client.get(response.url, follow=True)
        assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Check new org is OK.
        same_siret_orgs = PrescriberOrganization.objects.filter(siret=siret).order_by("kind").all()
        assert 2 == len(same_siret_orgs)
        org1, org2 = same_siret_orgs
        assert PrescriberOrganizationKind.ML.value == org1.kind
        assert PrescriberOrganizationKind.PLIE.value == org2.kind

    @respx.mock
    def test_join_new_organization_with_same_siret_and_same_kind(self, client, mocker):
        """
        A user can't create a new prescriber organization with an existing SIRET number if:
        * the kind of the new organization is the same as an existing one
        * there is no duplicate of the (kind, siret) pair
        """
        user = random_pro_user_factory(identity_provider=IdentityProvider.PRO_CONNECT)
        client.force_login(user)

        mock_call_ban_geocoding_api = mocker.patch(
            "itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK
        )
        # Same SIRET as mock but with same expected kind.
        siret = "26570134200148"
        respx.get(f"{settings.API_INSEE_SIRENE_URL}/siret/{siret}").mock(
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
        user = random_pro_user_factory()
        client.force_login(user)

        siret = "26570134200148"
        prescriber_org = PrescriberOrganizationFactory(
            siret=siret, membership__user__for_snapshot=True, for_snapshot=True, with_membership=True
        )
        prescriber_membership = prescriber_org.memberships.first()

        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": prescriber_org.siret,
            "department": prescriber_org.department,
        }
        response = client.post(url, data=post_data)
        assertContains(response, prescriber_org.display_name)
        assertContains(
            response,
            escape(
                "Si vous souhaitez rejoindre cette organisation, demandez à Pierre D. de vous ajouter "
                "en tant que collaborateur."
            ),
            html=True,
        )

        url = reverse("signup:prescriber_request_invitation", kwargs={"membership_id": prescriber_membership.id})
        response = client.get(url)
        assertContains(response, prescriber_org.display_name)
        assertContains(
            response,
            "Renseignez vos coordonnées afin d'être ajouté à l'organisation « Pres. Org. » par Pierre D.",
            html=True,
        )

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

    def test_hidden_organization_kinds(self, client, mocker):
        """
        HIDDEN_PRESCRIBER_KINDS should not be displayed or chosen in the form
        """
        user = random_pro_user_factory()
        client.force_login(user)

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


class TestPrescribersViewsExceptions:
    def test_organization_creation_error(self, client, pro_connect):
        """
        The organization creation didn't work.
        The user is still created and can try again.
        """
        org = PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.OTHER)
        user = random_pro_user_factory(
            email=pro_connect.oidc_userinfo["email"], username=pro_connect.oidc_userinfo["sub"]
        )
        client.force_login(user)

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

        response = client.get(reverse("signup:prescriber_join_org"))
        assertRedirects(response, reverse("signup:prescriber_check_already_exists"))
        assert not user.prescriberorganization_set.exists()

    def test_prescriber_signup_ft_organization_wrong_email(self, client, pro_connect):
        """
        A user creates a prescriber account on Itou with ProConnect
        He wants to join a Pôle emploi organization
        but his e-mail suffix is wrong. An error should be raised.
        """
        user = random_pro_user_factory()
        client.force_login(user)

        # Go through each step to ensure session data is recorded properly.
        # Step 1: choose organization kind or go to the "no organization" page.
        response = client.get(reverse("signup:prescriber_check_already_exists"))

        safir_step_url = reverse("signup:prescriber_search_ft_org")
        assertNotContains(response, safir_step_url)

        response = client.get(safir_step_url)
        assert response.status_code == 403

        ft_org = PrescriberOrganizationFactory(france_travail=True)
        join_step_url = reverse("signup:prescriber_join_ft_org", kwargs={"uuid": ft_org.uid})
        response = client.post(join_step_url)
        assert response.status_code == 403
        assert not user.prescriberorganization_set.exists()

    def test_permission_denied_when_skiping_first_step(self, client, subtests):
        client.force_login(random_pro_user_factory())
        urls = [
            reverse("signup:prescriber_request_invitation", kwargs={"membership_id": 1}),
            reverse("signup:prescriber_choose_org"),
            reverse("signup:prescriber_choose_kind"),
            reverse("signup:prescriber_confirm_authorization"),
            reverse("signup:prescriber_search_ft_org"),
            reverse("signup:prescriber_join_ft_org", kwargs={"uuid": uuid.uuid4()}),
            reverse("signup:prescriber_join_org"),
        ]
        for url in urls:
            with subtests.test(url=url):
                response = client.get(url)
                assert response.status_code == 403
