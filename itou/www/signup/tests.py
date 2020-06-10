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
from itou.prescribers.factories import (
    AuthorizedPrescriberOrganizationWithMembershipFactory,
    PrescriberOrganizationFactory,
    PrescriberOrganizationWithMembershipFactory,
    PrescriberPoleEmploiFactory,
)
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.factories import SiaeFactory, SiaeWithMembershipFactory
from itou.siaes.models import Siae
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory
from itou.www.signup.forms import SelectSiaeForm


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
        expected_error = _("Merci de renseigner un e-mail ou un numéro de SIRET connu de nos services.")
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
            self.assertRedirects(response, reverse("home:hp"))

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
            self.assertIn("[Action requise] Un nouvel utilisateur souhaite rejoindre votre structure", subjects)
            self.assertIn("Confirmer l'adresse email pour la Plateforme de l'inclusion", subjects)

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

        user_first_name = "Jessica"
        user_email = "jessica.doe@siae.com"

        siae = SiaeWithMembershipFactory(kind=Siae.KIND_ETTI)
        self.assertEqual(1, siae.members.count())

        token = siae.get_token()
        with mock.patch("itou.utils.tokens.SiaeSignupTokenGenerator.make_token", return_value=token):

            self.assertEqual(len(siae.active_admin_members), 1)
            existing_admin_user = siae.active_admin_members.first()

            url = reverse("signup:select_siae")
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)

            # Find an SIAE: (siret, kind) matches one SIAE.
            post_data = {"email": user_email, "siret": siae.siret, "kind": siae.kind}
            response = self.client.post(url, data=post_data)
            self.assertEqual(response.status_code, 302)
            self.assertRedirects(response, siae.signup_magic_link)

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
                "email": user_email,
                "password1": "!*p4ssw0rd123-",
                "password2": "!*p4ssw0rd123-",
            }
            response = self.client.post(url, data=post_data)
            self.assertEqual(response.status_code, 302)
            self.assertRedirects(response, reverse("account_email_verification_sent"))

            # Check `User` state.
            user = get_user_model().objects.get(email=user_email)
            self.assertFalse(user.is_job_seeker)
            self.assertFalse(user.is_prescriber)
            self.assertTrue(user.is_siae_staff)
            self.assertTrue(user.is_active)
            self.assertEqual(user.first_name, user_first_name)
            self.assertEqual(user.last_name, post_data["last_name"])
            self.assertEqual(user.email, user_email)
            # Check `Membership` state.
            self.assertTrue(siae.has_admin(existing_admin_user))
            self.assertFalse(siae.has_admin(user))
            self.assertEqual(2, siae.members.count())
            # Check `EmailAddress` state.
            self.assertEqual(user.emailaddress_set.count(), 1)
            user_email = user.emailaddress_set.first()
            self.assertFalse(user_email.verified)

            # Check sent emails.
            self.assertEqual(len(mail.outbox), 2)
            subjects = [email.subject for email in mail.outbox]
            self.assertIn("Un nouvel utilisateur vient de rejoindre votre structure", subjects)
            self.assertIn("Confirmer l'adresse email pour la Plateforme de l'inclusion", subjects)

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
        self.assertIn("Confirmer l'adresse email pour la Plateforme de l'inclusion", email.subject)
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
    def test_poleemploi_prescriber(self):
        url = reverse("signup:prescriber_poleemploi")
        response = self.client.get(url)

        organization = PrescriberPoleEmploiFactory()

        password = "!*p4ssw0rd123-"

        self.assertEqual(response.status_code, 200)
        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@pole-emploi.fr",
            "password1": password,
            "password2": password,
            "safir_code": organization.code_safir_pole_emploi,
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

        # Check membership
        self.assertIn(user, organization.members.all())
        self.assertEqual(1, user.prescriberorganization_set.count())

        # User validation via email tested in `test_prescriber_signup_without_code_nor_organization`

        # Check prescriber signup (email already exists)
        response = self.client.post(url, data=post_data)
        self.assertFormError(response, "form", "email", "Cette adresse email est déjà enregistrée")

    def test_authorized_prescriber_with_organization(self):
        url = reverse("signup:prescriber_authorized")
        response = self.client.get(url)

        authorized_organization = AuthorizedPrescriberOrganizationWithMembershipFactory()
        password = "!*p4ssw0rd123-"

        self.assertEqual(response.status_code, 200)
        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe+unregistered@prescriber.com",
            "password1": password,
            "password2": password,
            "authorized_organization_id": authorized_organization.pk,
        }
        response = self.client.post(url, data=post_data)

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        # User checks
        user = get_user_model().objects.get(email=post_data["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)
        # Check `EmailAddress` state.
        self.assertEqual(user.emailaddress_set.count(), 1)
        user_email = user.emailaddress_set.first()
        self.assertFalse(user_email.verified)

        # Check org.
        self.assertTrue(authorized_organization.is_authorized)
        self.assertEqual(
            authorized_organization.authorization_status, PrescriberOrganization.AuthorizationStatus.VALIDATED
        )

        # Check membership
        self.assertIn(user, authorized_organization.members.all())
        self.assertEqual(2, authorized_organization.members.count())
        self.assertEqual(1, user.prescriberorganization_set.count())
        membership = user.prescribermembership_set.get(organization=authorized_organization)
        self.assertFalse(membership.is_admin)

        # User validation via email tested in `test_prescriber_signup_without_code_nor_organization`

    def test_authorized_prescriber_with_no_member_organization(self):
        """
        When a prescriber is linked to an existing prescriber organization without any member,
        a specific email must be sent.
        """
        url = reverse("signup:prescriber_authorized")
        response = self.client.get(url)

        authorized_organization = PrescriberOrganizationFactory()
        password = "!*p4ssw0rd123-"

        self.assertEqual(response.status_code, 200)
        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe+unregistered@prescriber.com",
            "password1": password,
            "password2": password,
            "authorized_organization_id": authorized_organization.pk,
        }
        response = self.client.post(url, data=post_data)

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        # See previous tests for user / org assertions
        user = get_user_model().objects.get(email=post_data["email"])

        # Check membership
        self.assertIn(user, authorized_organization.members.all())
        self.assertEqual(1, authorized_organization.members.count())

        # Check email has been sent to support (validation/refusal of authorisation needed)
        self.assertEqual(len(mail.outbox), 2)
        subject = mail.outbox[0].subject
        self.assertIn("Première inscription à une organisation existante", subject)
        subject = mail.outbox[1].subject
        self.assertIn("Confirmer l'adresse email pour la Plateforme de l'inclusion", subject)

    def test_authorized_prescriber_without_registered_organization(self):
        url = reverse("signup:prescriber_authorized")
        response = self.client.get(url)

        organization_name = "UNREGISTERED_INC"
        password = "!*p4ssw0rd123-"

        self.assertEqual(response.status_code, 200)
        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe+unregistered@prescriber.com",
            "password1": password,
            "password2": password,
            "unregistered_organization": organization_name,
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

        # User validation via email tested in `test_prescriber_signup_without_code_nor_organization`

        # Check if a new organization is created
        new_org = PrescriberOrganization.objects.get(name=organization_name)
        self.assertFalse(new_org.is_authorized)
        self.assertEqual(new_org.authorization_status, PrescriberOrganization.AuthorizationStatus.NOT_SET)
        self.assertIsNone(new_org.authorization_updated_at)
        self.assertIsNone(new_org.authorization_updated_by)
        self.assertEqual(new_org.created_by, user)

        # Check membership
        self.assertEqual(1, new_org.members.count())
        self.assertIn(user, new_org.members.all())

        # Check email has been sent to support (validation/refusal of authorisation needed)
        self.assertEqual(len(mail.outbox), 2)
        subject = mail.outbox[0].subject
        self.assertIn("Vérification de l'habilitation d'une nouvelle organisation", subject)
        subject = mail.outbox[1].subject
        self.assertIn("Confirmer l'adresse email pour la Plateforme de l'inclusion", subject)

    def test_prescriber_signup_without_code_nor_organization(self):
        """
        Prescriber signup (orienter) without code nor organization.

        The full "email confirmation process" is tested here.
        Further Prescriber's signup tests doesn't have to fully test it again.
        """

        url = reverse("signup:prescriber_orienter")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        password = "!*p4ssw0rd123-"

        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@prescriber.com",
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

        # Check sent email.
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("Confirmer l'adresse email pour la Plateforme de l'inclusion", email.subject)
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

    def test_prescriber_signup_with_code_to_unauthorized_organization(self):
        """
        Prescriber signup (orienter) with a code to join an unauthorized organization.
        Organization has a pre-existing admin user who is notified of the signup.
        """
        organization = PrescriberOrganizationWithMembershipFactory()

        url = reverse("signup:prescriber_orienter")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        password = "!*p4ssw0rd123-"

        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@prescriber.com",
            "password1": password,
            "password2": password,
            "secret_code": organization.secret_code,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        # Check `User` state.
        user = get_user_model().objects.get(email=post_data["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)
        self.assertIn(user, organization.members.all())
        self.assertEqual(2, organization.members.count())
        membership = user.prescribermembership_set.get(organization=organization)
        self.assertFalse(membership.is_admin)
        # Check `EmailAddress` state.
        self.assertEqual(user.emailaddress_set.count(), 1)
        user_email = user.emailaddress_set.first()
        self.assertFalse(user_email.verified)

        # Check sent emails.
        self.assertEqual(len(mail.outbox), 2)
        subjects = [email.subject for email in mail.outbox]
        self.assertIn("Un nouvel utilisateur vient de rejoindre votre organisation", subjects)
        self.assertIn("Confirmer l'adresse email pour la Plateforme de l'inclusion", subjects)

    def test_second_member_signup_without_code_to_authorized_organization(self):
        """
        A second user signup to join an authorized organization.
        First one is notified when second one signs up.
        """

        # Create an authorized organization with one admin.
        authorized_organization = AuthorizedPrescriberOrganizationWithMembershipFactory()
        self.assertEqual(1, authorized_organization.members.count())
        first_user = authorized_organization.members.first()
        membership = first_user.prescribermembership_set.get(organization=authorized_organization)
        self.assertTrue(membership.is_admin)

        # A second user wants to join the authorized organization.
        url = reverse("signup:prescriber_orienter")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        password = "!*p4ssw0rd123-"

        post_data = {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane.doe@prescriber.com",
            "password1": password,
            "password2": password,
            "secret_code": authorized_organization.secret_code,
        }

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        # Check `User` state.
        second_user = get_user_model().objects.get(email=post_data["email"])
        self.assertFalse(second_user.is_job_seeker)
        self.assertFalse(second_user.is_siae_staff)
        self.assertTrue(second_user.is_prescriber)
        # Check `Membership` state.
        self.assertIn(second_user, authorized_organization.members.all())
        self.assertEqual(2, authorized_organization.members.count())
        self.assertEqual(1, second_user.prescriberorganization_set.count())
        membership = second_user.prescribermembership_set.get(organization=authorized_organization)
        self.assertFalse(membership.is_admin)

        # Check sent emails.
        self.assertEqual(len(mail.outbox), 2)
        subjects = [email.subject for email in mail.outbox]
        self.assertIn("Un nouvel utilisateur vient de rejoindre votre organisation", subjects)
        self.assertIn("Confirmer l'adresse email pour la Plateforme de l'inclusion", subjects)


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
        self.assertIn("Vous pouvez ignorer ce message en toute sécurité", email.body)
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
