import uuid
from unittest import mock

import httpx
import respx
from allauth.account.models import EmailConfirmationHMAC
from django.conf import settings
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.http import urlencode

from itou.prescribers.factories import (
    PrescriberOrganizationFactory,
    PrescriberOrganizationWithMembershipFactory,
    PrescriberPoleEmploiFactory,
)
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.factories import DEFAULT_PASSWORD
from itou.users.models import User
from itou.utils.mocks.api_entreprise import ETABLISSEMENT_API_RESULT_MOCK
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK
from itou.utils.password_validation import CnilCompositionPasswordValidator
from itou.www.signup.forms import PrescriberChooseKindForm


class PrescriberSignupTest(TestCase):
    def test_prescriber_is_pole_emploi(self):
        # GET
        self.assertNotIn("prescriber_signup", list(self.client.session.keys()))

        url = reverse("signup:prescriber_is_pole_emploi")
        response = self.client.get(url)
        self.assertContains(response, "Travaillez-vous pour Pôle emploi ?")

        # Data stored in session (on GET 🤦).
        self.assertIn("prescriber_signup", list(self.client.session.keys()))

        # POST Yes.
        response = self.client.post(url, data={"is_pole_emploi": 1})
        self.assertRedirects(response, reverse("signup:prescriber_pole_emploi_safir_code"))

        # POST No.
        response = self.client.post(url, data={"is_pole_emploi": 0})
        self.assertRedirects(response, reverse("signup:prescriber_siren"))

    def test_create_user_prescriber_member_of_pole_emploi(self):
        """
        Test the creation of a user of type prescriber and his joining to a Pole emploi agency.
        """

        organization = PrescriberPoleEmploiFactory()

        # Step 1: the user works for PE.
        url = reverse("signup:prescriber_is_pole_emploi")
        response = self.client.post(url, data={"is_pole_emploi": 1})

        # Step 2: fill the SAFIR code.
        url = reverse("signup:prescriber_pole_emploi_safir_code")
        self.assertRedirects(response, url)
        post_data = {
            "safir_code": organization.code_safir_pole_emploi,
        }
        response = self.client.post(url, data=post_data)

        # Step 3: fill the user information
        # Ensures that the parent form's clean() method is called by testing
        # with a password that does not comply with CNIL recommendations.
        url = reverse("signup:prescriber_pole_emploi_user")
        self.assertRedirects(response, url)
        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe+unregistered@prescriber.com",
            "password1": "foofoofoo",
            "password2": "foofoofoo",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertIn(CnilCompositionPasswordValidator.HELP_MSG, response.context["form"].errors["password1"])

        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": f"john.doe{settings.POLE_EMPLOI_EMAIL_SUFFIX}",
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
        }
        response = self.client.post(url, data=post_data)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        user = User.objects.get(email=post_data["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        # Check `EmailAddress` state.
        user_emails = user.emailaddress_set.all()
        self.assertEqual(len(user_emails), 1)
        user_email = user_emails[0]
        self.assertFalse(user_email.verified)

        # Check organization.
        self.assertTrue(organization.is_authorized)
        self.assertEqual(organization.authorization_status, PrescriberOrganization.AuthorizationStatus.VALIDATED)

        # Check membership.
        self.assertIn(user, organization.members.all())
        self.assertEqual(1, user.prescriberorganization_set.count())

        # Check sent email.
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("Confirmez votre adresse e-mail", email.subject)
        self.assertIn("Afin de finaliser votre inscription, cliquez sur le lien suivant", email.body)
        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(email.to[0], user.email)

        # User cannot log in until confirmation.
        post_data = {"login": user.email, "password": DEFAULT_PASSWORD}
        url = reverse("account_login")
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.url, reverse("account_email_verification_sent"))

        # Confirm email + auto login.
        confirmation_token = EmailConfirmationHMAC(user_email).key
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
        response = self.client.post(confirm_email_url)
        self.assertRedirects(response, reverse("welcoming_tour:index"))
        user_email = user.emailaddress_set.first()
        self.assertTrue(user_email.verified)

    @respx.mock
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_create_user_prescriber_with_authorized_org_of_known_kind(self, mock_call_ban_geocoding_api):
        """
        Test the creation of a user of type prescriber with an authorized organization of *known* kind.
        """

        siret = "11122233300001"

        # Step 1: the user doesn't work for PE.
        url = reverse("signup:prescriber_is_pole_emploi")
        response = self.client.post(url, data={"is_pole_emploi": 0})

        # Step 2: search organizations with SIREN and department.
        url = reverse("signup:prescriber_siren")
        self.assertRedirects(response, url)
        get_data = {
            "siren": siret[:9],
            "department": "67",
        }
        response = self.client.get(url, data=get_data)

        # Step 3: ask the user to choose the organization he's working for in a pre-existing list.
        url = reverse("signup:prescriber_choose_org")
        self.assertRedirects(response, url)
        post_data = {
            "kind": PrescriberOrganization.Kind.CAP_EMPLOI.value,
        }
        response = self.client.post(url, data=post_data)

        # Step 4: fill the SIRET number.
        respx.get(f"{settings.API_ENTREPRISE_BASE_URL}/etablissements/{siret}").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )
        url = reverse("signup:prescriber_siret")
        self.assertRedirects(response, url)
        post_data = {
            "partial_siret": siret[-5:],
        }
        response = self.client.post(url, data=post_data)
        mock_call_ban_geocoding_api.assert_called_once()

        # Step 5: user information.
        url = reverse("signup:prescriber_user")
        self.assertRedirects(response, url)
        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": f"john.doe{settings.POLE_EMPLOI_EMAIL_SUFFIX}",
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
        }
        response = self.client.post(url, data=post_data)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        # Check `User` state.
        user = User.objects.get(email=post_data["email"])
        # `username` should be a valid UUID, see `User.generate_unique_username()`.
        self.assertEqual(user.username, uuid.UUID(user.username, version=4).hex)
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        # Check `EmailAddress` state.
        user_emails = user.emailaddress_set.all()
        self.assertEqual(len(user_emails), 1)
        user_email = user_emails[0]
        self.assertFalse(user_email.verified)

        # Check organization.
        org = PrescriberOrganization.objects.get(siret=siret)
        self.assertFalse(org.is_authorized)
        self.assertEqual(org.authorization_status, PrescriberOrganization.AuthorizationStatus.NOT_SET)

        # Check membership.
        self.assertEqual(1, user.prescriberorganization_set.count())
        membership = user.prescribermembership_set.get(organization=org)
        self.assertTrue(membership.is_admin)

        # Check sent email.
        self.assertEqual(len(mail.outbox), 2)

        # Check email has been sent to support (validation/refusal of authorisation needed).
        email = mail.outbox[0]
        self.assertIn("Vérification de l'habilitation d'une nouvelle organisation", email.subject)

        # Check email has been sent to confirm the user's email.
        email = mail.outbox[1]
        self.assertIn("Confirmez votre adresse e-mail", email.subject)
        self.assertIn("Afin de finaliser votre inscription, cliquez sur le lien suivant", email.body)
        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(email.to[0], user.email)

        # User cannot log in until confirmation.
        post_data = {"login": user.email, "password": DEFAULT_PASSWORD}
        url = reverse("account_login")
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.url, reverse("account_email_verification_sent"))

        # Confirm email + auto login.
        confirmation_token = EmailConfirmationHMAC(user_email).key
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
        response = self.client.post(confirm_email_url)
        self.assertRedirects(response, reverse("welcoming_tour:index"))
        user_email = user.emailaddress_set.first()
        self.assertTrue(user_email.verified)

    @respx.mock
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_create_user_prescriber_with_authorized_org_of_unknown_kind(self, mock_call_ban_geocoding_api):
        """
        Test the creation of a user of type prescriber with an authorized organization of *unknown* kind.
        """

        siret = "11122233300001"

        # Step 1: the user doesn't work for PE.
        url = reverse("signup:prescriber_is_pole_emploi")
        response = self.client.post(url, data={"is_pole_emploi": 0})

        # Step 2: search organizations with SIREN and department.
        url = reverse("signup:prescriber_siren")
        self.assertRedirects(response, url)
        get_data = {
            "siren": siret[:9],
            "department": "67",
        }
        response = self.client.get(url, data=get_data)

        # Step 3: set 'other' organization.
        url = reverse("signup:prescriber_choose_org")
        self.assertRedirects(response, url)
        post_data = {
            "kind": PrescriberOrganization.Kind.OTHER.value,
        }
        response = self.client.post(url, data=post_data)

        # Step 4: ask the user his kind of prescriber.
        url = reverse("signup:prescriber_choose_kind")
        self.assertRedirects(response, url)
        post_data = {
            "kind": PrescriberChooseKindForm.KIND_AUTHORIZED_ORG,
        }
        response = self.client.post(url, data=post_data)

        # Step 5: ask the user to confirm the "authorized" character of his organization.
        url = reverse("signup:prescriber_confirm_authorization")
        self.assertRedirects(response, url)
        post_data = {
            "confirm_authorization": 1,
        }
        response = self.client.post(url, data=post_data)

        # Step 6: fill the SIRET number.
        api_entreprise_route = respx.get(f"{settings.API_ENTREPRISE_BASE_URL}/etablissements/{siret}").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )
        url = reverse("signup:prescriber_siret")
        self.assertRedirects(response, url)
        post_data = {
            "partial_siret": siret[-5:],
        }
        response = self.client.post(url, data=post_data)
        self.assertTrue(api_entreprise_route.called)
        mock_call_ban_geocoding_api.assert_called_once()

        # Step 7: fill the user information.
        url = reverse("signup:prescriber_user")
        self.assertRedirects(response, url)
        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": f"john.doe{settings.POLE_EMPLOI_EMAIL_SUFFIX}",
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
        }
        response = self.client.post(url, data=post_data)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        # Check `User` state.
        user = User.objects.get(email=post_data["email"])
        # `username` should be a valid UUID, see `User.generate_unique_username()`.
        self.assertEqual(user.username, uuid.UUID(user.username, version=4).hex)
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        # Check `EmailAddress` state.
        user_emails = user.emailaddress_set.all()
        self.assertEqual(len(user_emails), 1)
        self.assertFalse(user_emails[0].verified)

        # Check org.
        org = PrescriberOrganization.objects.get(siret=siret)
        self.assertFalse(org.is_authorized)
        self.assertEqual(org.authorization_status, PrescriberOrganization.AuthorizationStatus.NOT_SET)

        # Check membership.
        self.assertEqual(1, user.prescriberorganization_set.count())
        membership = user.prescribermembership_set.get(organization=org)
        self.assertTrue(membership.is_admin)

        # Check email has been sent to support (validation/refusal of authorisation needed).
        self.assertEqual(len(mail.outbox), 2)
        subject = mail.outbox[0].subject
        self.assertIn("Vérification de l'habilitation d'une nouvelle organisation", subject)
        # Full email validation process is tested in `test_create_user_prescriber_with_authorized_org_of_known_kind`.
        subject = mail.outbox[1].subject
        self.assertIn("Confirmez votre adresse e-mail", subject)

    @respx.mock
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_create_user_prescriber_with_unauthorized_org(self, mock_call_ban_geocoding_api):
        """
        Test the creation of a user of type prescriber with an unauthorized organization.
        """

        siret = "11122233300001"

        # Step 1: the user doesn't work for PE.
        url = reverse("signup:prescriber_is_pole_emploi")
        response = self.client.post(url, data={"is_pole_emploi": 0})
        url = reverse("signup:prescriber_siren")
        self.assertRedirects(response, url)

        # Step 2: search organizations with SIREN and department.
        get_data = {
            "siren": siret[:9],
            "department": "67",
        }
        response = self.client.get(url, data=get_data)

        # Step 3: select kind of organization.
        url = reverse("signup:prescriber_choose_org")
        self.assertRedirects(response, url)
        post_data = {
            "kind": PrescriberOrganization.Kind.OTHER.value,
        }
        response = self.client.post(url, data=post_data)

        # Step 4: select the kind of prescriber 'UNAUTHORIZED'.
        url = reverse("signup:prescriber_choose_kind")
        self.assertRedirects(response, url)
        post_data = {
            "kind": PrescriberChooseKindForm.KIND_UNAUTHORIZED_ORG,
        }
        response = self.client.post(url, data=post_data)

        # Step 5: fill the SIRET number.
        url = reverse("signup:prescriber_siret")
        self.assertRedirects(response, url)
        api_entreprise_route = respx.get(f"{settings.API_ENTREPRISE_BASE_URL}/etablissements/{siret}").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )
        post_data = {
            "partial_siret": siret[-5:],
        }
        response = self.client.post(url, data=post_data)
        self.assertTrue(api_entreprise_route.called)
        mock_call_ban_geocoding_api.assert_called_once()

        # Step 6: user information.
        url = reverse("signup:prescriber_user")
        self.assertRedirects(response, url)
        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": f"john.doe{settings.POLE_EMPLOI_EMAIL_SUFFIX}",
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
        }
        response = self.client.post(url, data=post_data)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        # Check `User` state.
        user = User.objects.get(email=post_data["email"])
        # `username` should be a valid UUID, see `User.generate_unique_username()`.
        self.assertEqual(user.username, uuid.UUID(user.username, version=4).hex)
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        # Check `EmailAddress` state
        user_emails = user.emailaddress_set.all()
        self.assertEqual(len(user_emails), 1)
        self.assertFalse(user_emails[0].verified)

        # Check organization.
        org = PrescriberOrganization.objects.get(siret=siret)
        self.assertFalse(org.is_authorized)
        self.assertEqual(org.authorization_status, PrescriberOrganization.AuthorizationStatus.NOT_REQUIRED)

        # Check membership.
        self.assertEqual(1, user.prescriberorganization_set.count())
        membership = user.prescribermembership_set.get(organization=org)
        self.assertTrue(membership.is_admin)

        # Full email validation process is tested in `test_create_user_prescriber_with_authorized_org_of_known_kind`.
        self.assertEqual(len(mail.outbox), 1)
        subject = mail.outbox[0].subject
        self.assertIn("Confirmez votre adresse e-mail", subject)

    def test_create_user_prescriber_with_existing_siren_other_department(self):
        """
        Test the creation of a user of type prescriber with existing SIREN but in an other department
        """

        siret = "26570134200148"

        # PrescriberOrganizationWithMembershipFactory.
        PrescriberOrganizationWithMembershipFactory(
            siret=siret, kind=PrescriberOrganization.Kind.SPIP, department="01"
        )

        # Step 1: the user doesn't work for PE.
        url = reverse("signup:prescriber_is_pole_emploi")
        response = self.client.post(url, data={"is_pole_emploi": 0})

        # Step 2: ask the user the SIREN number and departement of the organization.
        url = reverse("signup:prescriber_siren")
        self.assertRedirects(response, url)
        get_data = {
            "siren": siret[:9],
            "department": "67",
        }
        response = self.client.get(url, data=get_data)
        url = reverse("signup:prescriber_choose_org")
        self.assertRedirects(response, url)

    def test_create_user_prescriber_with_existing_siren_same_department(self):
        """
        Test the creation of a user of type prescriber with existing SIREN in a same department
        """
        siret = "26570134200148"

        existing_org_with_siret = PrescriberOrganizationWithMembershipFactory(
            siret=siret, kind=PrescriberOrganization.Kind.SPIP, department="67"
        )

        # Step 1: the user doesn't work for PE.
        url = reverse("signup:prescriber_is_pole_emploi")
        response = self.client.post(url, data={"is_pole_emploi": 0})

        # Step 2: search organizations with SIREN and department.
        url = reverse("signup:prescriber_siren")
        self.assertRedirects(response, url)
        get_data = {
            "siren": siret[:9],
            "department": "67",
        }
        response = self.client.get(url, data=get_data)
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

        siret = "26570134200148"

        PrescriberOrganizationFactory(siret=siret, kind=PrescriberOrganization.Kind.SPIP, department="67")

        # Step 1: the user doesn't work for PE.
        url = reverse("signup:prescriber_is_pole_emploi")
        response = self.client.post(
            url,
            data={"is_pole_emploi": 0},
        )

        # Step 2: search organizations with SIREN and department.
        url = reverse("signup:prescriber_siren")
        self.assertRedirects(response, url)
        get_data = {
            "siren": siret[:9],
            "department": "67",
        }
        response = self.client.get(url, data=get_data)
        url = reverse("signup:prescriber_choose_org")
        self.assertRedirects(response, url)

    def test_create_user_prescriber_without_org(self):
        """
        Test the creation of a user of type prescriber without organization.
        """

        # Step 1: the user doesn't work for PE.
        url = reverse("signup:prescriber_is_pole_emploi")
        response = self.client.post(
            url,
            data={"is_pole_emploi": 0},
        )

        # Step 2: redirected on search.
        url = reverse("signup:prescriber_siren")
        self.assertRedirects(response, url)

        # Step 3: the user clicks on "No organization" in search of organization
        # (SIREN and department).
        response = self.client.get(url)
        user_info_url = reverse("signup:prescriber_user")
        self.assertContains(response, user_info_url)
        response = self.client.get(user_info_url)
        self.assertEqual(response.status_code, 200)

        # Step 3: fill the user information.
        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": f"john.doe{settings.POLE_EMPLOI_EMAIL_SUFFIX}",
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
        }
        response = self.client.post(user_info_url, data=post_data)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        # Check `User` state.
        user = User.objects.get(email=post_data["email"])
        # `username` should be a valid UUID, see `User.generate_unique_username()`.
        self.assertEqual(user.username, uuid.UUID(user.username, version=4).hex)
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        # Check `EmailAddress` state.
        self.assertEqual(user.emailaddress_set.count(), 1)
        user_email = user.emailaddress_set.first()
        self.assertFalse(user_email.verified)

        # Check membership.
        self.assertEqual(0, user.prescriberorganization_set.count())

        # Full email validation process is tested in
        # `test_create_user_prescriber_with_authorized_org_of_known_kind`.
        self.assertEqual(len(mail.outbox), 1)
        subject = mail.outbox[0].subject
        self.assertIn("Confirmez votre adresse e-mail", subject)

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
        respx.get(f"{settings.API_ENTREPRISE_BASE_URL}/etablissements/{siret}").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )
        PrescriberOrganizationFactory(siret=siret, kind=PrescriberOrganization.Kind.ML)

        # Step 1: the user doesn't work for PE.
        url = reverse("signup:prescriber_is_pole_emploi")
        post_data = {
            "is_pole_emploi": 0,
        }
        self.client.post(url, data=post_data)

        url = reverse("signup:prescriber_siren")
        get_data = {
            "siren": siret[:9],
            "department": "67",
        }
        self.client.get(url, data=get_data)

        url = reverse("signup:prescriber_choose_org")
        post_data = {"kind": PrescriberOrganization.Kind.PLIE.value}
        self.client.post(url, data=post_data)

        url = reverse("signup:prescriber_siret")
        post_data = {
            "partial_siret": siret[-5:],
        }
        response = self.client.post(url, data=post_data)

        url = reverse("signup:prescriber_user")
        self.assertRedirects(response, url)
        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@ma-plie.fr",
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
        }
        response = self.client.post(url, data=post_data)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        # Check new org is OK.
        same_siret_orgs = PrescriberOrganization.objects.filter(siret=siret).order_by("kind").all()
        self.assertEqual(2, len(same_siret_orgs))
        org1, org2 = same_siret_orgs
        self.assertEqual(PrescriberOrganization.Kind.ML.value, org1.kind)
        self.assertEqual(PrescriberOrganization.Kind.PLIE.value, org2.kind)

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
        respx.get(f"{settings.API_ENTREPRISE_BASE_URL}/etablissements/{siret}").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )
        prescriber_organization = PrescriberOrganizationFactory(siret=siret, kind=PrescriberOrganization.Kind.PLIE)

        post_data = {
            "is_pole_emploi": 0,
        }
        url = reverse("signup:prescriber_is_pole_emploi")
        response = self.client.post(url, data=post_data)

        url = reverse("signup:prescriber_siren")
        self.assertRedirects(response, url)
        get_data = {"siren": siret[:9], "department": "01"}
        response = self.client.get(url, data=get_data)

        url = reverse("signup:prescriber_choose_org")
        self.assertRedirects(response, url)
        post_data = {
            "kind": PrescriberOrganization.Kind.PLIE.value,
        }
        response = self.client.post(url, data=post_data)

        url = reverse("signup:prescriber_siret")
        self.assertRedirects(response, url)
        post_data = {
            "partial_siret": siret[-5:],
        }
        response = self.client.post(url, data=post_data)
        self.assertContains(response, f"« {prescriber_organization.display_name} » utilise déjà ce SIRET.")

    def test_form_to_request_for_an_invitation(self):
        prescriber_org = PrescriberOrganizationWithMembershipFactory()
        prescriber_membership = prescriber_org.prescribermembership_set.first()

        url = reverse("signup:prescriber_request_invitation", kwargs={"membership_id": prescriber_membership.id})
        response = self.client.get(url)
        self.assertContains(response, prescriber_org.display_name)

        response = self.client.post(url, data={"first_name": "Bertrand", "last_name": "Martin", "email": "beber"})
        self.assertContains(response, "Saisissez une adresse e-mail valide.")

        requestor = {"first_name": "Bertrand", "last_name": "Martin", "email": "bertand@wahoo.fr"}
        response = self.client.post(url, data=requestor)
        self.assertEqual(response.status_code, 302)

        self.assertEqual(len(mail.outbox), 1)
        mail_body = mail.outbox[0].body
        self.assertIn(prescriber_membership.user.first_name.capitalize(), mail_body)
        self.assertIn(prescriber_membership.organization.display_name, mail_body)
        invitation_url = "%s?%s" % (reverse("invitations_views:invite_prescriber_with_org"), urlencode(requestor))
        self.assertIn(invitation_url, mail_body)
