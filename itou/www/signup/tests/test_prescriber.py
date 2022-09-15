from unittest import mock

import httpx
import respx
from django.conf import settings
from django.contrib import auth
from django.contrib.messages import get_messages
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape
from django.utils.http import urlencode
from django.utils.safestring import mark_safe

from itou.openid_connect.inclusion_connect.constants import INCLUSION_CONNECT_SESSION_KEY
from itou.openid_connect.inclusion_connect.tests import OIDC_USERINFO, mock_oauth_dance
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.factories import (
    PrescriberOrganizationFactory,
    PrescriberOrganizationWithMembershipFactory,
    PrescriberPoleEmploiFactory,
)
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.enums import KIND_PRESCRIBER
from itou.users.factories import PrescriberFactory, SiaeStaffFactory
from itou.users.models import User
from itou.utils.mocks.api_entreprise import ETABLISSEMENT_API_RESULT_MOCK, INSEE_API_RESULT_MOCK
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK
from itou.www.signup.forms import PrescriberChooseKindForm


class PrescriberSignupTest(TestCase):
    def setUp(self):
        super().setUp()

        respx.post(f"{settings.API_INSEE_BASE_URL}/token").mock(
            return_value=httpx.Response(200, json=INSEE_API_RESULT_MOCK)
        )
        respx.get(f"{settings.API_ENTREPRISE_BASE_URL}/siret/26570134200148").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )

    @respx.mock
    def test_create_user_prescriber_member_of_pole_emploi(self):
        """
        Test the creation of a user of type prescriber and his joining to a Pole emploi agency.
        """

        organization = PrescriberPoleEmploiFactory()

        # Go through each step to ensure session data is recorded properly.
        # Step 1: the user works for PE follows PE link
        url = reverse("signup:prescriber_check_already_exists")
        response = self.client.get(url)
        safir_step_url = reverse("signup:prescriber_pole_emploi_safir_code")
        self.assertContains(response, safir_step_url)

        # Step 2: find PE organization by SAFIR code.
        response = self.client.get(url)
        post_data = {"safir_code": organization.code_safir_pole_emploi}
        response = self.client.post(safir_step_url, data=post_data)

        # Step 3: check email
        url = reverse("signup:prescriber_check_pe_email")
        self.assertRedirects(response, url)
        post_data = {"email": "athos@lestroismousquetaires.com"}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("email"))

        email = f"athos{settings.POLE_EMPLOI_EMAIL_SUFFIX}"
        post_data = {"email": email}
        response = self.client.post(url, data=post_data)
        self.assertRedirects(response, reverse("signup:prescriber_pole_emploi_user"))
        session_data = self.client.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
        self.assertEqual(email, session_data.get("email"))

        response = self.client.get(response.url)
        self.assertContains(response, "inclusion_connect_button.svg")
        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_pole_emploi_user")
        next_url = reverse("signup:prescriber_join_org")
        params = {
            "login_hint": email,
            "channel": "pole_emploi",
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        # Connect with Inclusion Connect.
        response = mock_oauth_dance(
            self,
            KIND_PRESCRIBER,
            assert_redirects=False,
            login_hint=email,
            channel="pole_emploi",
            user_info_email=email,
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)
        self.assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Organization
        self.assertEqual(self.client.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY), organization.pk)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, f"Code SAFIR {organization.code_safir_pole_emploi}")

        user = User.objects.get(email=email)
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        user_emails = user.emailaddress_set.all()
        # Emails are not checked in Django anymore.
        # Make sure no confirmation email is sent.
        self.assertEqual(len(user_emails), 0)

        # Check organization.
        self.assertTrue(organization.is_authorized)
        self.assertEqual(organization.authorization_status, PrescriberAuthorizationStatus.VALIDATED)

        # Check membership.
        self.assertEqual(1, user.prescriberorganization_set.count())
        self.assertEqual(user.prescribermembership_set.count(), 1)
        self.assertEqual(user.prescribermembership_set.get().organization_id, organization.pk)
        self.assertEqual(user.siae_set.count(), 0)

    @respx.mock
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_create_user_prescriber_with_authorized_org_of_known_kind(self, mock_call_ban_geocoding_api):
        """
        Test the creation of a user of type prescriber with an authorized organization of *known* kind.
        """

        siret = "26570134200148"

        # Step 1: search organizations with SIRET
        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret,
            "department": "67",
        }
        response = self.client.post(url, data=post_data)

        # Step 2: ask the user to choose the organization he's working for in a pre-existing list.
        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret})
        self.assertRedirects(response, url)
        post_data = {
            "kind": PrescriberOrganizationKind.CAP_EMPLOI.value,
        }
        response = self.client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_called_once()

        # Step 3: Inclusion Connect button
        url = reverse("signup:prescriber_user")
        self.assertRedirects(response, url)
        response = self.client.get(url)
        self.assertContains(response, "inclusion_connect_button.svg")
        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_user")
        next_url = reverse("signup:prescriber_join_org")
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        response = mock_oauth_dance(
            self,
            KIND_PRESCRIBER,
            assert_redirects=False,
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)
        self.assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Check `User` state.
        user = User.objects.get(email=OIDC_USERINFO["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        # Check `EmailAddress` state.
        user_emails = user.emailaddress_set.all()
        # Emails are not checked in Django anymore.
        # Make sure no confirmation email is sent.
        self.assertEqual(len(user_emails), 0)

        # Check organization.
        org = PrescriberOrganization.objects.get(siret=siret)
        self.assertFalse(org.is_authorized)
        self.assertEqual(org.authorization_status, PrescriberAuthorizationStatus.NOT_SET)

        # Check membership.
        self.assertEqual(1, user.prescriberorganization_set.count())
        self.assertEqual(user.prescribermembership_set.count(), 1)
        membership = user.prescribermembership_set.get(organization=org)
        self.assertTrue(membership.is_admin)

    @respx.mock
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_create_user_prescriber_with_authorized_org_of_unknown_kind(self, mock_call_ban_geocoding_api):
        """
        Test the creation of a user of type prescriber with an authorized organization of *unknown* kind.
        """

        siret = "26570134200148"

        # Step 1: search organizations with SIRET
        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret,
            "department": "67",
        }
        response = self.client.post(url, data=post_data)

        # Step 2: set 'other' organization.
        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret})
        self.assertRedirects(response, url)
        post_data = {
            "kind": PrescriberOrganizationKind.OTHER.value,
        }
        response = self.client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_called_once()

        # Step 3: ask the user his kind of prescriber.
        url = reverse("signup:prescriber_choose_kind")
        self.assertRedirects(response, url)
        post_data = {
            "kind": PrescriberChooseKindForm.KIND_AUTHORIZED_ORG,
        }
        response = self.client.post(url, data=post_data)

        # Step 4: ask the user to confirm the "authorized" character of his organization.
        url = reverse("signup:prescriber_confirm_authorization")
        self.assertRedirects(response, url)
        post_data = {
            "confirm_authorization": 1,
        }
        response = self.client.post(url, data=post_data)

        # Step 5: Inclusion Connect button
        url = reverse("signup:prescriber_user")
        self.assertRedirects(response, url)
        response = self.client.get(url)
        self.assertContains(response, "inclusion_connect_button.svg")
        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_user")
        next_url = reverse("signup:prescriber_join_org")
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        previous_url = reverse("signup:prescriber_user")
        response = mock_oauth_dance(
            self,
            KIND_PRESCRIBER,
            assert_redirects=False,
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)
        self.assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Check `User` state.
        user = User.objects.get(email=OIDC_USERINFO["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        # Check `EmailAddress` state.
        user_emails = user.emailaddress_set.all()
        # Emails are not checked in Django anymore.
        # Make sure no confirmation email is sent.
        self.assertEqual(len(user_emails), 0)

        # Check organization.
        org = PrescriberOrganization.objects.get(siret=siret)
        self.assertFalse(org.is_authorized)
        self.assertEqual(org.authorization_status, PrescriberAuthorizationStatus.NOT_SET)

        # Check membership.
        self.assertEqual(1, user.prescriberorganization_set.count())
        self.assertEqual(user.prescribermembership_set.count(), 1)
        membership = user.prescribermembership_set.get(organization=org)
        self.assertTrue(membership.is_admin)

        # Check email has been sent to support (validation/refusal of authorisation needed).
        self.assertEqual(len(mail.outbox), 1)
        subject = mail.outbox[0].subject
        self.assertIn("Vérification de l'habilitation d'une nouvelle organisation", subject)

    @respx.mock
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_create_user_prescriber_with_unauthorized_org(self, mock_call_ban_geocoding_api):
        """
        Test the creation of a user of type prescriber with an unauthorized organization.
        """

        siret = "26570134200148"

        # Step 1: search organizations with SIRET
        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret,
            "department": "67",
        }
        response = self.client.post(url, data=post_data)

        # Step 2: select kind of organization.
        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret})
        self.assertRedirects(response, url)
        post_data = {
            "kind": PrescriberOrganizationKind.OTHER.value,
        }
        response = self.client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_called_once()

        # Step 3: select the kind of prescriber 'UNAUTHORIZED'.
        url = reverse("signup:prescriber_choose_kind")
        self.assertRedirects(response, url)
        post_data = {
            "kind": PrescriberChooseKindForm.KIND_UNAUTHORIZED_ORG,
        }
        response = self.client.post(url, data=post_data)

        # Step 4: Inclusion Connect button
        url = reverse("signup:prescriber_user")
        self.assertRedirects(response, url)
        response = self.client.get(url)
        self.assertContains(response, "inclusion_connect_button.svg")
        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_user")
        next_url = reverse("signup:prescriber_join_org")
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        response = mock_oauth_dance(
            self,
            KIND_PRESCRIBER,
            assert_redirects=False,
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)
        self.assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Check `User` state.
        user = User.objects.get(email=OIDC_USERINFO["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        # Check `EmailAddress` state.
        user_emails = user.emailaddress_set.all()
        # Emails are not checked in Django anymore.
        # Make sure no confirmation email is sent.
        self.assertEqual(len(user_emails), 0)

        # Check organization.
        org = PrescriberOrganization.objects.get(siret=siret)
        self.assertFalse(org.is_authorized)
        self.assertEqual(org.authorization_status, PrescriberAuthorizationStatus.NOT_REQUIRED)

        # Check membership.
        self.assertEqual(1, user.prescriberorganization_set.count())
        self.assertEqual(user.prescribermembership_set.count(), 1)
        membership = user.prescribermembership_set.get(organization=org)
        self.assertTrue(membership.is_admin)

        # No email has been sent to support (validation/refusal of authorisation not needed).
        self.assertEqual(len(mail.outbox), 0)

    def test_create_user_prescriber_with_existing_siren_other_department(self):
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
        response = self.client.post(url, data=post_data)

        # Step 2: redirect to kind of organization selection.
        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret2})
        self.assertRedirects(response, url)

    def test_create_user_prescriber_with_existing_siren_same_department(self):
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
        response = self.client.post(url, data=post_data)
        self.assertContains(response, existing_org_with_siret.display_name)

        # Request for an invitation link.
        prescriber_membership = (
            PrescriberMembership.objects.filter(organization=existing_org_with_siret)
            .active()
            .select_related("user")
            .order_by("-is_admin", "joined_at")
            .first()
        )
        self.assertContains(
            response,
            reverse("signup:prescriber_request_invitation", kwargs={"membership_id": prescriber_membership.id}),
        )

        # New organization link.
        self.assertContains(response, reverse("signup:prescriber_choose_org"))

    def test_create_user_prescriber_with_existing_siren_without_member(self):
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
        response = self.client.post(url, data=post_data)

        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret2})
        self.assertRedirects(response, url)

    @respx.mock
    def test_create_user_prescriber_without_org(self):
        """
        Test the creation of a user of type prescriber without organization.
        """

        # Step 1: the user clicks on "No organization" in search of organization
        # (SIREN and department).
        url = reverse("signup:prescriber_check_already_exists")
        response = self.client.get(url)

        # Step 2: Inclusion Connect button
        url = reverse("signup:prescriber_user")
        self.assertContains(response, url)
        response = self.client.get(url)
        self.assertContains(response, "inclusion_connect_button.svg")
        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_user")
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        response = mock_oauth_dance(
            self,
            KIND_PRESCRIBER,
            assert_redirects=False,
            previous_url=previous_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)
        self.assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Check `User` state.
        user = User.objects.get(email=OIDC_USERINFO["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        # Check `EmailAddress` state.
        user_emails = user.emailaddress_set.all()
        # Emails are not checked in Django anymore.
        # Make sure no confirmation email is sent.
        self.assertEqual(len(user_emails), 0)

        # Check membership.
        self.assertEqual(0, user.prescriberorganization_set.count())

        # No email has been sent to support (validation/refusal of authorisation not needed).
        self.assertEqual(len(mail.outbox), 0)

    @respx.mock
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_create_user_prescriber_with_same_siret_and_different_kind(self, mock_call_ban_geocoding_api):
        """
        A user can create a new prescriber organization with an existing SIRET number,
        provided that:
        - the kind of the new organization is different from the existing one
        - there is no duplicate of the (kind, siret) pair

        Example cases:
        - user can't create 2 PLIE with the same SIRET
        - user can create a PLIE and a ML with the same SIRET
        """

        # Same SIRET as mock.
        siret = "26570134200148"
        respx.get(f"{settings.API_ENTREPRISE_BASE_URL}/siret/{siret}").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )
        existing_org_with_siret = PrescriberOrganizationFactory(siret=siret, kind=PrescriberOrganizationKind.ML)

        # Step 1: search organizations with SIRET
        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret,
            "department": "67",
        }
        response = self.client.post(url, data=post_data)
        self.assertContains(response, existing_org_with_siret.display_name)

        # Step 2: Select kind
        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret})
        post_data = {"kind": PrescriberOrganizationKind.PLIE.value}
        response = self.client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_called_once()

        # Step 3: Inclusion Connect button
        url = reverse("signup:prescriber_user")
        self.assertRedirects(response, url)
        response = self.client.get(url)
        self.assertContains(response, "inclusion_connect_button.svg")
        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_user")
        next_url = reverse("signup:prescriber_join_org")
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        response = mock_oauth_dance(
            self,
            KIND_PRESCRIBER,
            assert_redirects=False,
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)
        self.assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Check new org is OK.
        same_siret_orgs = PrescriberOrganization.objects.filter(siret=siret).order_by("kind").all()
        self.assertEqual(2, len(same_siret_orgs))
        org1, org2 = same_siret_orgs
        self.assertEqual(PrescriberOrganizationKind.ML.value, org1.kind)
        self.assertEqual(PrescriberOrganizationKind.PLIE.value, org2.kind)

    @respx.mock
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_create_user_prescriber_with_same_siret_and_same_kind(self, mock_call_ban_geocoding_api):
        """
        A user can't create a new prescriber organization with an existing SIRET number if:
        * the kind of the new organization is the same as an existing one
        * there is no duplicate of the (kind, siret) pair
        """

        # Same SIRET as mock but with same expected kind.
        siret = "26570134200148"
        respx.get(f"{settings.API_ENTREPRISE_BASE_URL}/siret/{siret}").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )
        prescriber_organization = PrescriberOrganizationFactory(siret=siret, kind=PrescriberOrganizationKind.PLIE)

        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": siret,
            "department": "67",
        }
        response = self.client.post(url, data=post_data)

        self.assertContains(response, prescriber_organization.display_name)

        url = reverse("signup:prescriber_choose_org", kwargs={"siret": siret})
        post_data = {
            "kind": PrescriberOrganizationKind.PLIE.value,
        }
        response = self.client.post(url, data=post_data)
        self.assertContains(response, mark_safe("utilise déjà ce type d'organisation avec le même SIRET"))
        mock_call_ban_geocoding_api.assert_called_once()

    def test_form_to_request_for_an_invitation(self):
        siret = "26570134200148"
        prescriber_org = PrescriberOrganizationWithMembershipFactory(siret=siret)
        prescriber_membership = prescriber_org.prescribermembership_set.first()

        url = reverse("signup:prescriber_check_already_exists")
        post_data = {
            "siret": prescriber_org.siret,
            "department": prescriber_org.department,
        }
        response = self.client.post(url, data=post_data)
        self.assertContains(response, prescriber_org.display_name)

        url = reverse("signup:prescriber_request_invitation", kwargs={"membership_id": prescriber_membership.id})
        response = self.client.get(url)
        self.assertContains(response, prescriber_org.display_name)

        response = self.client.post(url, data={"first_name": "Bertrand", "last_name": "Martin", "email": "beber"})
        self.assertContains(response, "Saisissez une adresse e-mail valide.")

        requestor = {"first_name": "Bertrand", "last_name": "Martin", "email": "bertand@wahoo.fr"}
        response = self.client.post(url, data=requestor)
        self.assertEqual(response.status_code, 302)

        self.assertEqual(len(mail.outbox), 1)
        mail_subject = mail.outbox[0].subject
        self.assertIn(f"Demande pour rejoindre {prescriber_org.display_name}", mail_subject)
        mail_body = mail.outbox[0].body
        self.assertIn(prescriber_membership.user.get_full_name().title(), mail_body)
        self.assertIn(prescriber_membership.organization.display_name, mail_body)
        invitation_url = f'{reverse("invitations_views:invite_prescriber_with_org")}?{urlencode(requestor)}'
        self.assertIn(invitation_url, mail_body)

    @respx.mock
    def test_prescriber_already_exists__simple_signup(self):
        """
        He does not want to join an organization, only create an account.
        He likely forgot he had an account.
        He will be logged in instead as if he just used the login through IC button
        """
        #### User is a prescriber. Update it and connect. ####
        PrescriberFactory(email=OIDC_USERINFO["email"])
        self.client.get(reverse("signup:prescriber_check_already_exists"))

        # Step 2: register as a simple prescriber (orienteur).
        response = self.client.get(reverse("signup:prescriber_user"))
        self.assertContains(response, "inclusion_connect_button.svg")
        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_user")
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        # Connect with Inclusion Connect.
        response = mock_oauth_dance(
            self,
            KIND_PRESCRIBER,
            assert_redirects=False,
            previous_url=previous_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)
        self.assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        user = User.objects.get(email=OIDC_USERINFO["email"])
        self.assertTrue(user.has_sso_provider)

    @respx.mock
    def test_prescriber_already_exists__create_organization(self):
        """
        User is already a prescriber.
        We should update his account and make him join this new organization.
        """
        org = PrescriberOrganizationFactory.build(kind=PrescriberOrganizationKind.OTHER)
        user = PrescriberFactory(email=OIDC_USERINFO["email"])

        self.client.get(reverse("signup:prescriber_check_already_exists"))

        session_signup_data = self.client.session.get(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
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

        client_session = self.client.session
        client_session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = session_signup_data
        client_session.save()
        signup_url = reverse("signup:prescriber_user")

        response = self.client.get(signup_url)
        self.assertContains(response, "inclusion_connect_button.svg")
        # Check IC will redirect to the correct url
        previous_url = reverse("signup:prescriber_user")
        next_url = reverse("signup:prescriber_join_org")
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        # Connect with Inclusion Connect.
        response = mock_oauth_dance(
            self,
            KIND_PRESCRIBER,
            assert_redirects=False,
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)
        self.assertTemplateUsed(response, "welcoming_tour/prescriber.html")

        # Check organization
        org = PrescriberOrganization.objects.get(siret=org.siret)
        self.assertFalse(org.is_authorized)
        self.assertEqual(org.authorization_status, PrescriberAuthorizationStatus.NOT_SET)

        # Check membership.
        self.assertEqual(user.prescribermembership_set.count(), 1)
        membership = user.prescribermembership_set.get(organization=org)
        self.assertTrue(membership.is_admin)


class InclusionConnectPrescribersViewsExceptionsTest(TestCase):
    """
    Prescribers' signup and login exceptions: user already exists, ...
    """

    @respx.mock
    def test_organization_creation_error(self):
        """
        The organization creation didn't work.
        The user is still created and can try again.
        """
        org = PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.OTHER)
        user = PrescriberFactory(email=OIDC_USERINFO["email"])

        self.client.get(reverse("signup:prescriber_check_already_exists"))

        session_signup_data = self.client.session.get(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
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

        client_session = self.client.session
        client_session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = session_signup_data
        client_session.save()
        signup_url = reverse("signup:prescriber_user")

        response = self.client.get(signup_url)
        self.assertContains(response, "inclusion_connect_button.svg")

        # Connect with Inclusion Connect.
        previous_url = reverse("signup:prescriber_user")
        next_url = reverse("signup:prescriber_join_org")
        response = mock_oauth_dance(
            self,
            KIND_PRESCRIBER,
            assert_redirects=False,
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)
        self.assertTemplateNotUsed(response, "welcoming_tour/prescriber.html")

        # The user should be logged out and redirected to the home page.
        self.assertFalse(self.client.session.get(INCLUSION_CONNECT_SESSION_KEY))
        self.assertFalse(auth.get_user(self.client).is_authenticated)
        self.assertRedirects(response, reverse("home:hp"))

        # Check user was created but did not join an organisation
        user = User.objects.get(email=OIDC_USERINFO["email"])
        self.assertFalse(user.prescriberorganization_set.exists())

    @respx.mock
    def test_employer_already_exists(self):
        """
        User is already a member of an SIAE.
        Raise an exception.
        """
        org = PrescriberOrganizationFactory.build(kind=PrescriberOrganizationKind.OTHER)
        user = SiaeStaffFactory(email=OIDC_USERINFO["email"])
        self.client.get(reverse("signup:prescriber_check_already_exists"))

        session_signup_data = self.client.session.get(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
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

        client_session = self.client.session
        client_session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = session_signup_data
        client_session.save()
        signup_url = reverse("signup:prescriber_user")

        response = self.client.get(signup_url)
        self.assertContains(response, "inclusion_connect_button.svg")

        # Connect with Inclusion Connect.
        previous_url = reverse("signup:prescriber_user")
        next_url = reverse("signup:prescriber_join_org")
        response = mock_oauth_dance(
            self,
            KIND_PRESCRIBER,
            assert_redirects=False,
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)

        # Show an error and don't create an organization.
        self.assertEqual(response.wsgi_request.path, signup_url)
        self.assertTemplateNotUsed(response, "welcoming_tour/prescriber.html")
        self.assertContains(response, "inclusion_connect_button.svg")
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        error_message = "Un compte employeur existe déjà avec cette adresse e-mail"
        self.assertIn(error_message, str(messages[0]))

        user = User.objects.get(email=OIDC_USERINFO["email"])
        self.assertNotEqual(user.first_name, OIDC_USERINFO["given_name"])
        organization_exists = PrescriberOrganization.objects.filter(siret=org.siret).exists()
        self.assertFalse(organization_exists)
        self.assertFalse(user.prescriberorganization_set.exists())

    @respx.mock
    def test_prescriber_signup__pe_organization_wrong_email(self):
        """
        A user creates a prescriber account on Itou with Inclusion Connect.
        He wants to join a Pôle emploi organization
        but his e-mail suffix is wrong. An error should be raised.
        """
        pe_org = PrescriberPoleEmploiFactory()
        pe_email = f"athos{settings.POLE_EMPLOI_EMAIL_SUFFIX}"

        # Go through each step to ensure session data is recorded properly.
        # Step 1: choose organization kind or go to the "no organization" page.
        self.client.get(reverse("signup:prescriber_check_already_exists"))

        # Step 2: find PE organization by SAFIR code.
        safir_step_url = reverse("signup:prescriber_pole_emploi_safir_code")
        response = self.client.get(safir_step_url)
        post_data = {"safir_code": pe_org.code_safir_pole_emploi}
        response = self.client.post(safir_step_url, data=post_data, follow=True)

        # Step 3: check email
        check_email_url = reverse("signup:prescriber_check_pe_email")
        post_data = {"email": pe_email}
        response = self.client.post(check_email_url, data=post_data, follow=True)
        self.assertContains(response, "inclusion_connect_button.svg")

        # Connect with Inclusion Connect but, this time, don't use a PE email.
        previous_url = reverse("signup:prescriber_pole_emploi_user")
        next_url = reverse("signup:prescriber_join_org")
        wrong_email = "athos@touspourun.com"
        response = mock_oauth_dance(
            self,
            KIND_PRESCRIBER,
            login_hint=pe_email,
            channel="pole_emploi",
            assert_redirects=False,
            previous_url=previous_url,
            next_url=next_url,
            user_info_email=wrong_email,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)

        # Response should contain elements available only to prescribers on the welcoming tour.
        self.assertTemplateNotUsed(response, "welcoming_tour/prescriber.html")
        self.assertContains(response, "inclusion_connect_button.svg")
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn(
            "est différente de celle que vous avez indiquée précédemment",
            str(messages[0]),
        )

        # Organization
        self.assertFalse(self.client.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY))
        self.assertFalse(User.objects.filter(email=pe_email).exists())

    def test_permission_denied_when_skiping_first_step(self):
        urls = [
            reverse("signup:prescriber_request_invitation", kwargs={"membership_id": 1}),
            reverse("signup:prescriber_choose_org"),
            reverse("signup:prescriber_choose_kind"),
            reverse("signup:prescriber_confirm_authorization"),
            reverse("signup:prescriber_pole_emploi_safir_code"),
            reverse("signup:prescriber_check_pe_email"),
            reverse("signup:prescriber_pole_emploi_user"),
            reverse("signup:prescriber_user"),
            reverse("signup:prescriber_join_org"),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)
