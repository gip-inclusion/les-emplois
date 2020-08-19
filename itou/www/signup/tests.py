from unittest import mock

from allauth.account.forms import default_token_generator
from allauth.account.models import EmailConfirmationHMAC
from allauth.account.utils import user_pk_to_url_str
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape
from django.utils.translation import gettext as _

from itou.cities.factories import create_test_cities
from itou.cities.models import City
from itou.prescribers.factories import PrescriberPoleEmploiFactory
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.factories import SiaeFactory, SiaeWithMembershipFactory
from itou.siaes.models import Siae
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory
from itou.utils.mocks.api_entreprise import ETABLISSEMENT_API_RESULT_MOCK
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK
from itou.utils.password_validation import CnilCompositionPasswordValidator
from itou.www.signup.forms import PrescriberIdentifyKindForm, SelectSiaeForm


class SignupTest(TestCase):
    def test_allauth_signup_url_override(self):
        """Ensure that the default allauth signup URL is overridden."""
        ALLAUTH_SIGNUP_URL = reverse("account_signup")
        self.assertEqual(ALLAUTH_SIGNUP_URL, "/accounts/signup/")
        response = self.client.get(ALLAUTH_SIGNUP_URL)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "signup/signup.html")
        response = self.client.post(ALLAUTH_SIGNUP_URL, data={"foo": "bar"})
        self.assertEqual(response.status_code, 405)


class SiaeSignupFormTest(TestCase):
    def test_select_siae_form_errors(self):
        """
        Test SelectSiaeForm errors.
        """

        # Missing email and SIRET.
        post_data = {"kind": Siae.KIND_ACI}
        form = SelectSiaeForm(data=post_data)
        form.is_valid()
        expected_error = _(
            "Merci de renseigner l'e-mail utilisé par le référent technique ASP"
            " ou un numéro de SIRET connu de nos services."
        )
        self.assertIn(expected_error, form.errors["__all__"])

        # (email, kind) or (siret, kind) does not match any siae.
        post_data = {"email": "daniela.doe@siae.com", "siret": "12345678901234", "kind": Siae.KIND_ACI}
        form = SelectSiaeForm(data=post_data)
        form.is_valid()
        expected_error = _("Votre numéro de SIRET ou votre e-mail nous sont inconnus.")
        self.assertTrue(form.errors["__all__"][0].startswith(expected_error))

        # (email, kind) matches two siaes, (siret, kind) does not match any siae.
        user_email = "emilie.doe@siae.com"
        SiaeFactory.create_batch(2, kind=Siae.KIND_ACI, auth_email=user_email)
        post_data = {"email": user_email, "siret": "12345678901234", "kind": Siae.KIND_ACI}
        form = SelectSiaeForm(data=post_data)
        form.is_valid()
        expected_error = _("Votre e-mail est partagé par plusieurs structures")
        self.assertTrue(form.errors["__all__"][0].startswith(expected_error))

    def test_select_siae_form_priority(self):
        """
        Test SelectSiaeForm priority.
        """

        # Priority is given to SIRET match over email match.
        user_email = "david.doe@siae.com"
        siae1 = SiaeFactory(kind=Siae.KIND_ACI, auth_email=user_email)
        siae2 = SiaeFactory(kind=Siae.KIND_ACI, auth_email=user_email)
        siae3 = SiaeWithMembershipFactory(kind=Siae.KIND_ACI, siret="12345678901234")
        post_data = {"email": user_email, "siret": siae3.siret, "kind": Siae.KIND_ACI}
        form = SelectSiaeForm(data=post_data)
        form.is_valid()
        self.assertEqual(form.selected_siae, siae3)

        # Priority is given to (siret, kind) when same SIRET is used for 2 SIAEs.
        siae1 = SiaeWithMembershipFactory(kind=Siae.KIND_ETTI)
        siae2 = SiaeFactory(kind=Siae.KIND_ACI, siret=siae1.siret)  # noqa F841
        post_data = {"email": user_email, "siret": siae1.siret, "kind": siae1.kind}
        form = SelectSiaeForm(data=post_data)
        form.is_valid()
        self.assertEqual(form.selected_siae, siae1)


class SiaeSignupTest(TestCase):
    def test_join_an_siae_without_members(self):
        """
        A user joins an SIAE without members.

        The full "email confirmation process" is tested here.
        Further Siae's signup tests doesn't have to fully test it again.
        """

        user_first_name = "Jacques"
        user_email = "jacques.doe@siae.com"
        user_secondary_email = "jacques.doe@hotmail.com"
        password = "!*p4ssw0rd123-"

        siae = SiaeFactory(kind=Siae.KIND_ETTI)
        self.assertEqual(0, siae.members.count())

        token = siae.get_token()
        with mock.patch("itou.utils.tokens.SiaeSignupTokenGenerator.make_token", return_value=token):

            url = reverse("signup:select_siae")
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)

            # Find an SIAE: (siret, kind) matches one SIAE.
            post_data = {"email": user_email, "siret": siae.siret, "kind": siae.kind}
            response = self.client.post(url, data=post_data)
            self.assertEqual(response.status_code, 302)
            self.assertRedirects(response, "/")

            self.assertEqual(len(mail.outbox), 1)
            email = mail.outbox[0]
            self.assertIn("Un nouvel utilisateur souhaite rejoindre votre structure", email.subject)

            magic_link = siae.signup_magic_link
            response = self.client.get(magic_link)
            self.assertEqual(response.status_code, 200)

            # No error when opening magic link a second time.
            response = self.client.get(magic_link)
            self.assertEqual(response.status_code, 200)

            # Create user.
            url = reverse("signup:siae")
            post_data = {
                # Hidden fields.
                "encoded_siae_id": siae.get_encoded_siae_id(),
                "token": siae.get_token(),
                # Readonly fields.
                "siret": siae.siret,
                "kind": siae.kind,
                "siae_name": siae.display_name,
                # Regular fields.
                "first_name": user_first_name,
                "last_name": "Doe",
                "email": user_secondary_email,
                "password1": password,
                "password2": password,
            }
            response = self.client.post(url, data=post_data)
            self.assertEqual(response.status_code, 302)
            self.assertRedirects(response, reverse("account_email_verification_sent"))

            self.assertFalse(get_user_model().objects.filter(email=user_email).exists())
            user = get_user_model().objects.get(email=user_secondary_email)

            # Check `User` state.
            self.assertFalse(user.is_job_seeker)
            self.assertFalse(user.is_prescriber)
            self.assertTrue(user.is_siae_staff)
            self.assertTrue(user.is_active)
            self.assertTrue(siae.has_admin(user))
            self.assertEqual(1, siae.members.count())
            self.assertEqual(user.first_name, user_first_name)
            self.assertEqual(user.last_name, post_data["last_name"])
            self.assertEqual(user.email, user_secondary_email)
            # Check `EmailAddress` state.
            self.assertEqual(user.emailaddress_set.count(), 1)
            user_email = user.emailaddress_set.first()
            self.assertFalse(user_email.verified)

            # Check sent email.
            self.assertEqual(len(mail.outbox), 2)
            subjects = [email.subject for email in mail.outbox]
            self.assertIn("[Action requise] Un nouvel utilisateur souhaite rejoindre votre structure !", subjects)
            self.assertIn("Confirmez votre adresse e-mail pour la Plateforme", subjects)

            # Magic link is no longer valid because siae.members.count() has changed.
            response = self.client.get(magic_link, follow=True)
            redirect_url, status_code = response.redirect_chain[-1]
            self.assertEqual(status_code, 302)
            next_url = reverse("signup:select_siae")
            self.assertEqual(redirect_url, next_url)
            self.assertEqual(response.status_code, 200)
            expected_message = _(
                "Ce lien d'inscription est invalide ou a expiré. " "Veuillez procéder à une nouvelle inscription."
            )
            self.assertContains(response, escape(expected_message))

            # User cannot log in until confirmation.
            post_data = {"login": user.email, "password": password}
            url = reverse("account_login")
            response = self.client.post(url, data=post_data)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse("account_email_verification_sent"))

            # Confirm email + auto login.
            confirmation_token = EmailConfirmationHMAC(user_email).key
            confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
            response = self.client.post(confirm_email_url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse("dashboard:index"))
            user_email = user.emailaddress_set.first()
            self.assertTrue(user_email.verified)

    def test_join_an_siae_with_one_member(self):
        """
        A user joins an SIAE with an existing member.
        """

        user_first_name = "Jessica"  # noqa F841
        user_email = "jessica.doe@siae.com"

        siae = SiaeWithMembershipFactory(kind=Siae.KIND_ETTI)
        self.assertEqual(1, siae.members.count())

        token = siae.get_token()
        with mock.patch("itou.utils.tokens.SiaeSignupTokenGenerator.make_token", return_value=token):

            self.assertEqual(len(siae.active_admin_members), 1)

            url = reverse("signup:select_siae")
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)

            # Find an SIAE: (siret, kind) matches one SIAE.
            post_data = {"email": user_email, "siret": siae.siret, "kind": siae.kind}
            response = self.client.post(url, data=post_data)
            self.assertEqual(response.status_code, 302)
            # Joining a structure with members is allowed only using the invitations feature.
            self.assertRedirects(response, "/")

    def test_cannot_join_an_inactive_siae(self):
        """
        A user cannot join an inactive SIAE.
        """

        user_first_name = "Judas"  # noqa F841
        user_email = "judas.iscariot@siae.com"

        siae = SiaeFactory(kind=Siae.KIND_ETTI, is_active=False)
        self.assertEqual(0, siae.members.count())

        token = siae.get_token()
        with mock.patch("itou.utils.tokens.SiaeSignupTokenGenerator.make_token", return_value=token):

            url = reverse("signup:select_siae")
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)

            # Find an SIAE: (siret, kind) matches one SIAE.
            post_data = {"email": user_email, "siret": siae.siret, "kind": siae.kind}
            response = self.client.post(url, data=post_data)
            self.assertEqual(response.status_code, 200)

            expected_message = _("La structure que vous souhaitez rejoindre n'est plus active à ce jour.")
            self.assertContains(response, expected_message)

    def test_legacy_route(self):
        """
        Opening the old route without any magic link credentials
        should nicely redirect the user to the correct signup url.
        """
        url = reverse("signup:siae")
        response = self.client.get(url, follow=True)
        redirect_url, status_code = response.redirect_chain[-1]
        self.assertEqual(status_code, 302)
        next_url = reverse("signup:select_siae")
        self.assertEqual(redirect_url, next_url)
        self.assertEqual(response.status_code, 200)
        expected_message = _(
            "Ce lien d'inscription est invalide ou a expiré. " "Veuillez procéder à une nouvelle inscription."
        )
        self.assertContains(response, escape(expected_message))


class JobSeekerSignupTest(TestCase):
    def setUp(self):
        create_test_cities(["67"], num_per_department=1)

    def test_job_seeker_signup(self):
        """Job-seeker signup."""

        url = reverse("signup:job_seeker")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        password = "!*p4ssw0rd123-"
        address_line_1 = "Test adresse"
        address_line_2 = "Test adresse complémentaire"
        city = City.objects.first()
        post_code = city.post_codes[0]
        resume_link = "https://test.com/my-cv"

        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@siae.com",
            "password1": password,
            "password2": password,
            "address_line_1": address_line_1,
            "address_line_2": address_line_2,
            "post_code": post_code,
            "city_name": city.name,
            "city": city.slug,
            "resume_link": resume_link,
        }

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        # Check `User` state.
        user = get_user_model().objects.get(email=post_data["email"])
        self.assertTrue(user.is_job_seeker)
        self.assertFalse(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        # Check `EmailAddress` state.
        self.assertEqual(user.emailaddress_set.count(), 1)
        user_email = user.emailaddress_set.first()
        self.assertFalse(user_email.verified)

        # Check sent email.
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("Confirmez votre adresse e-mail pour la Plateforme", email.subject)
        self.assertIn("Afin de finaliser votre inscription, cliquez sur le lien suivant", email.body)
        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(email.to[0], user.email)

        # User cannot log in until confirmation.
        post_data = {"login": user.email, "password": password}
        url = reverse("account_login")
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("account_email_verification_sent"))

        # Confirm email + auto login.
        confirmation_token = EmailConfirmationHMAC(user_email).key
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
        response = self.client.post(confirm_email_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:index"))
        user_email = user.emailaddress_set.first()
        self.assertTrue(user_email.verified)


class PrescriberSignupTest(TestCase):
    def test_create_user_prescriber_member_of_pole_emploi(self):
        """
        Test the creation of a user of type prescriber and his joining to a Pole emploi agency.
        """

        organization = PrescriberPoleEmploiFactory()

        # Step 1: do the user work for PE?

        url = reverse("signup:prescriber_is_pole_emploi")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "is_pole_emploi": 1,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_pole_emploi_safir_code")
        self.assertRedirects(response, url)

        # Step 2: ask the user his SAFIR code.

        post_data = {
            "safir_code": organization.code_safir_pole_emploi,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_pole_emploi_user")
        self.assertRedirects(response, url)

        # Step 3: user info.

        # Ensures that the parent form's clean() method is called by testing
        # with a password that does not comply with CNIL recommendations.
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

        password = "!*p4ssw0rd123-"
        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@pole-emploi.fr",
            "password1": password,
            "password2": password,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        user = get_user_model().objects.get(email=post_data["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        # Check `EmailAddress` state.
        self.assertEqual(user.emailaddress_set.count(), 1)
        user_email = user.emailaddress_set.first()
        self.assertFalse(user_email.verified)

        # Check org.
        self.assertTrue(organization.is_authorized)
        self.assertEqual(organization.authorization_status, PrescriberOrganization.AuthorizationStatus.VALIDATED)

        # Check membership.
        self.assertIn(user, organization.members.all())
        self.assertEqual(1, user.prescriberorganization_set.count())

        # Check sent email.
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("Confirmez votre adresse e-mail pour la Plateforme", email.subject)
        self.assertIn("Afin de finaliser votre inscription, cliquez sur le lien suivant", email.body)
        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(email.to[0], user.email)

        # User cannot log in until confirmation.
        post_data = {"login": user.email, "password": password}
        url = reverse("account_login")
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("account_email_verification_sent"))

        # Confirm email + auto login.
        confirmation_token = EmailConfirmationHMAC(user_email).key
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
        response = self.client.post(confirm_email_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:index"))
        user_email = user.emailaddress_set.first()
        self.assertTrue(user_email.verified)

    @mock.patch(
        "itou.utils.apis.api_entreprise.EtablissementAPI.get", return_value=(ETABLISSEMENT_API_RESULT_MOCK, None)
    )
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_create_user_prescriber_with_authorized_org_of_known_kind(
        self, mock_api_entreprise, mock_call_ban_geocoding_api
    ):
        """
        Test the creation of a user of type prescriber with an authorized organization of *known* kind.
        """

        siret = "11122233300001"

        # Step 1: do the user work for PE?

        url = reverse("signup:prescriber_is_pole_emploi")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "is_pole_emploi": 0,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_is_known_org")
        self.assertRedirects(response, url)

        # Step 2: ask the user to choose the organization he's working for in a pre-existing list.

        post_data = {
            "kind": PrescriberOrganization.Kind.CAP_EMPLOI.value,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_confirm_authorization")
        self.assertRedirects(response, url)

        # Step 3: ask the user to confirm the "authorized" character of his organization.

        post_data = {
            "confirm_authorization": 1,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_siret")
        self.assertRedirects(response, url)

        # Step 4: ask the user his SIRET number.

        post_data = {
            "siret": siret,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_user")
        self.assertRedirects(response, url)
        mock_api_entreprise.assert_called_once()
        mock_call_ban_geocoding_api.assert_called_once()

        # Step 5: user info.

        password = "!*p4ssw0rd123-"
        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@pole-emploi.fr",
            "password1": password,
            "password2": password,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        # Check `User` state.
        user = get_user_model().objects.get(email=post_data["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        # Check `EmailAddress` state.
        self.assertEqual(user.emailaddress_set.count(), 1)
        user_email = user.emailaddress_set.first()
        self.assertFalse(user_email.verified)

        # Check org.
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
        self.assertIn("Confirmez votre adresse e-mail pour la Plateforme", email.subject)
        self.assertIn("Afin de finaliser votre inscription, cliquez sur le lien suivant", email.body)
        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(email.to[0], user.email)

        # User cannot log in until confirmation.
        post_data = {"login": user.email, "password": password}
        url = reverse("account_login")
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("account_email_verification_sent"))

        # Confirm email + auto login.
        confirmation_token = EmailConfirmationHMAC(user_email).key
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
        response = self.client.post(confirm_email_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:index"))
        user_email = user.emailaddress_set.first()
        self.assertTrue(user_email.verified)

    @mock.patch(
        "itou.utils.apis.api_entreprise.EtablissementAPI.get", return_value=(ETABLISSEMENT_API_RESULT_MOCK, None)
    )
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_create_user_prescriber_with_authorized_org_of_unknown_kind(
        self, mock_api_entreprise, mock_call_ban_geocoding_api
    ):
        """
        Test the creation of a user of type prescriber with an authorized organization of *unknown* kind.
        """

        siret = "11122233300001"

        # Step 1: Does the user work  for PE?

        url = reverse("signup:prescriber_is_pole_emploi")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "is_pole_emploi": 0,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_is_known_org")
        self.assertRedirects(response, url)

        # Step 2: ask the user to choose the organization he's working for in a pre-existing list.

        post_data = {
            "kind": PrescriberOrganization.Kind.OTHER.value,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_ask_kind")
        self.assertRedirects(response, url)

        # Step 3: ask the user his kind of prescriber.
        post_data = {
            "kind": PrescriberIdentifyKindForm.KIND_AUTHORIZED_ORG,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_confirm_authorization")
        self.assertRedirects(response, url)

        # Step 4: ask the user to confirm the "authorized" character of his organization.

        post_data = {
            "confirm_authorization": 1,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_siret")
        self.assertRedirects(response, url)

        # Step 5: ask the user his SIRET number.

        post_data = {
            "siret": siret,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_user")
        self.assertRedirects(response, url)
        mock_api_entreprise.assert_called_once()
        mock_call_ban_geocoding_api.assert_called_once()

        # Step 6: user info.

        password = "!*p4ssw0rd123-"
        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@pole-emploi.fr",
            "password1": password,
            "password2": password,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        # Check `User` state.
        user = get_user_model().objects.get(email=post_data["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        # Check `EmailAddress` state.
        self.assertEqual(user.emailaddress_set.count(), 1)
        user_email = user.emailaddress_set.first()
        self.assertFalse(user_email.verified)

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
        # Full email validation process is tested in `test_create_user_prescriber_with_authorized_org_of_known_kind`
        subject = mail.outbox[1].subject
        self.assertIn("Confirmez votre adresse e-mail pour la Plateforme", subject)

    @mock.patch(
        "itou.utils.apis.api_entreprise.EtablissementAPI.get", return_value=(ETABLISSEMENT_API_RESULT_MOCK, None)
    )
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_create_user_prescriber_with_unauthorized_org(self, mock_api_entreprise, mock_call_ban_geocoding_api):
        """
        Test the creation of a user of type prescriber with an unauthorized organization.
        """

        siret = "11122233300001"

        # Step 1: Does the user work  for PE?

        url = reverse("signup:prescriber_is_pole_emploi")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "is_pole_emploi": 0,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_is_known_org")
        self.assertRedirects(response, url)

        # Step 2: ask the user to choose the organization he's working for in a pre-existing list.

        post_data = {
            "kind": PrescriberOrganization.Kind.OTHER.value,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_ask_kind")
        self.assertRedirects(response, url)

        # Step 3: ask the user his kind of prescriber.

        post_data = {
            "kind": PrescriberIdentifyKindForm.KIND_UNAUTHORIZED_ORG,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_siret")
        self.assertRedirects(response, url)

        # Step 4: ask the user his SIRET number.

        post_data = {
            "siret": siret,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_user")
        self.assertRedirects(response, url)
        mock_api_entreprise.assert_called_once()
        mock_call_ban_geocoding_api.assert_called_once()

        # Step 5: user info.

        password = "!*p4ssw0rd123-"
        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@pole-emploi.fr",
            "password1": password,
            "password2": password,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        # Check `User` state.
        user = get_user_model().objects.get(email=post_data["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        # Check `EmailAddress` state.
        self.assertEqual(user.emailaddress_set.count(), 1)
        user_email = user.emailaddress_set.first()
        self.assertFalse(user_email.verified)

        # Check org.
        org = PrescriberOrganization.objects.get(siret=siret)
        self.assertFalse(org.is_authorized)
        self.assertEqual(org.authorization_status, PrescriberOrganization.AuthorizationStatus.NOT_REQUIRED)

        # Check membership.
        self.assertEqual(1, user.prescriberorganization_set.count())
        membership = user.prescribermembership_set.get(organization=org)
        self.assertTrue(membership.is_admin)

        # Full email validation process is tested in `test_create_user_prescriber_with_authorized_org_of_known_kind`
        self.assertEqual(len(mail.outbox), 1)
        subject = mail.outbox[0].subject
        self.assertIn("Confirmez votre adresse e-mail pour la Plateforme", subject)

    def test_create_user_prescriber_without_org(self):
        """
        Test the creation of a user of type prescriber without organization.
        """

        # Step 1: Does the user work  for PE?

        url = reverse("signup:prescriber_is_pole_emploi")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "is_pole_emploi": 0,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_is_known_org")
        self.assertRedirects(response, url)

        # Step 2: ask the user to choose the organization he's working for in a pre-existing list.

        post_data = {
            "kind": PrescriberOrganization.Kind.OTHER.value,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_ask_kind")
        self.assertRedirects(response, url)

        # Step 3: ask the user his kind of prescriber.

        post_data = {
            "kind": PrescriberIdentifyKindForm.KIND_SOLO,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        url = reverse("signup:prescriber_user")
        self.assertRedirects(response, url)

        # Step 4: user info.

        password = "!*p4ssw0rd123-"
        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@pole-emploi.fr",
            "password1": password,
            "password2": password,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        # Check `User` state.
        user = get_user_model().objects.get(email=post_data["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        # Check `EmailAddress` state.
        self.assertEqual(user.emailaddress_set.count(), 1)
        user_email = user.emailaddress_set.first()
        self.assertFalse(user_email.verified)

        # Check membership.
        self.assertEqual(0, user.prescriberorganization_set.count())

        # Full email validation process is tested in `test_create_user_prescriber_with_authorized_org_of_known_kind`
        self.assertEqual(len(mail.outbox), 1)
        subject = mail.outbox[0].subject
        self.assertIn("Confirmez votre adresse e-mail pour la Plateforme", subject)


class PasswordResetTest(TestCase):
    def test_password_reset_flow(self):

        user = JobSeekerFactory()

        # Ask for password reset.
        url = reverse("account_reset_password")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        post_data = {"email": user.email}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("account_reset_password_done"))

        # Check sent email.
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("Réinitialisation de votre mot de passe", email.subject)
        self.assertIn(
            "Si vous n'avez pas demandé la réinitialisation de votre mot de passe, vous pouvez ignorer ce message",
            email.body,
        )
        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(email.to[0], user.email)

        # Change forgotten password.
        uidb36 = user_pk_to_url_str(user)
        key = default_token_generator.make_token(user)
        password_change_url = reverse("account_reset_password_from_key", kwargs={"uidb36": uidb36, "key": key})
        response = self.client.get(password_change_url)
        password_change_url_with_hidden_key = response.url
        post_data = {"password1": "Mlkjhgf!sq2", "password2": "Mlkjhgf!sq2"}
        response = self.client.post(password_change_url_with_hidden_key, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("account_reset_password_from_key_done"))

        # User can log in with his new password.
        self.assertTrue(self.client.login(username=user.email, password="Mlkjhgf!sq2"))
        self.client.logout()

    def test_password_reset_with_nonexistent_email(self):
        """
        Avoid user enumeration: redirect to the success page even with a nonexistent email.
        """
        url = reverse("account_reset_password")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        post_data = {"email": "nonexistent@email.com"}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("account_reset_password_done"))


class PasswordChangeTest(TestCase):
    def test_password_change_flow(self):
        """
        Ensure that the default allauth account_change_password URL is overridden
        and redirects to the right place.
        """

        user = JobSeekerFactory()
        self.assertTrue(self.client.login(username=user.email, password=DEFAULT_PASSWORD))

        # Change password.
        url = reverse("account_change_password")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        post_data = {"oldpassword": DEFAULT_PASSWORD, "password1": "Mlkjhgf!sq2", "password2": "Mlkjhgf!sq2"}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("dashboard:index"))

        # User can log in with his new password.
        self.client.logout()
        self.assertTrue(self.client.login(username=user.email, password="Mlkjhgf!sq2"))
        self.client.logout()
