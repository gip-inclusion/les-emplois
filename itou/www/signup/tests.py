from allauth.account.forms import default_token_generator
from allauth.account.utils import user_pk_to_url_str

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from itou.prescribers.factories import PrescriberOrganizationFactory
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory

from itou.siaes.factories import SiaeFactory
from itou.siaes.models import Siae
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory


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

    def test_siae_signup(self):
        """SIAE signup."""

        siae = SiaeFactory()

        url = reverse("signup:siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@siae.com",
            "siret": siae.siret,
            "password1": "!*p4ssw0rd123-",
            "password2": "!*p4ssw0rd123-",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        user = get_user_model().objects.get(email=post_data["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertFalse(user.is_prescriber)
        self.assertTrue(user.is_siae_staff)

        siae = Siae.active_objects.get(siret=post_data["siret"])
        self.assertTrue(user.siaemembership_set.get(siae=siae).is_siae_admin)
        self.assertEqual(1, siae.members.count())

    def test_siae_signup_when_two_siaes_have_the_same_siret(self):
        """SIAE signup using a SIRET shared by two siaes."""

        siae1 = SiaeFactory()
        siae1.name = "FIRST SIAE"
        siae1.kind = Siae.KIND_ETTI
        siae1.save()

        siae2 = SiaeFactory()
        siae2.name = "SECOND SIAE"
        siae2.kind = Siae.KIND_ACI
        siae2.siret = siae1.siret
        siae2.save()

        url = reverse("signup:siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@siae.com",
            "siret": siae1.siret,
            "password1": "!*p4ssw0rd123-",
            "password2": "!*p4ssw0rd123-",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        user = get_user_model().objects.get(email=post_data["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertFalse(user.is_prescriber)
        self.assertTrue(user.is_siae_staff)

        siae1 = Siae.active_objects.get(name=siae1.name)
        self.assertTrue(user.siaemembership_set.get(siae=siae1).is_siae_admin)
        self.assertEqual(1, siae1.members.count())

        siae2 = Siae.active_objects.get(name=siae2.name)
        self.assertTrue(user.siaemembership_set.get(siae=siae2).is_siae_admin)
        self.assertEqual(1, siae2.members.count())

    def test_job_seeker_signup(self):
        """Job-seeker signup."""

        url = reverse("signup:job_seeker")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@siae.com",
            "password1": "!*p4ssw0rd123-",
            "password2": "!*p4ssw0rd123-",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        user = get_user_model().objects.get(email=post_data["email"])
        self.assertTrue(user.is_job_seeker)
        self.assertFalse(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)


class PrescriberSignupTest(TestCase):
    def test_prescriber_signup_without_code(self):
        """Prescriber signup without code."""

        url = reverse("signup:prescriber")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@prescriber.com",
            "password1": "!*p4ssw0rd123-",
            "password2": "!*p4ssw0rd123-",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        user = get_user_model().objects.get(email=post_data["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        self.assertEqual(0, user.prescriberorganization_set.count())

    def test_prescriber_signup_with_code(self):
        """Prescriber signup with a code to join an organization."""

        organization = PrescriberOrganizationWithMembershipFactory()

        url = reverse("signup:prescriber")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@prescriber.com",
            "password1": "!*p4ssw0rd123-",
            "password2": "!*p4ssw0rd123-",
            "secret_code": organization.secret_code,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        user = get_user_model().objects.get(email=post_data["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        self.assertIn(user, organization.members.all())
        self.assertEqual(2, organization.members.count())

        self.assertIn(organization, user.prescriberorganization_set.all())
        self.assertEqual(1, user.prescriberorganization_set.count())

        membership = user.prescribermembership_set.get(organization=organization)
        self.assertFalse(membership.is_admin)

    def test_prescriber_signup_join_authorized_organization(self):
        """Prescriber signup who joins an authorized_organization."""

        authorized_organization = PrescriberOrganizationFactory(
            is_authorized=True, department="62"
        )

        url = reverse("signup:prescriber")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@prescriber.com",
            "password1": "!*p4ssw0rd123-",
            "password2": "!*p4ssw0rd123-",
            "authorized_organization": authorized_organization.pk,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        user = get_user_model().objects.get(email=post_data["email"])
        self.assertFalse(user.is_job_seeker)
        self.assertTrue(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        self.assertIn(user, authorized_organization.members.all())
        self.assertEqual(1, authorized_organization.members.count())
        self.assertEqual(1, user.prescriberorganization_set.count())

        membership = user.prescribermembership_set.get(
            organization=authorized_organization
        )
        self.assertTrue(membership.is_admin)


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
        password_change_url = reverse(
            "account_reset_password_from_key", kwargs={"uidb36": uidb36, "key": key}
        )
        response = self.client.get(password_change_url)
        password_change_url_with_hidden_key = response.url
        post_data = {"password1": "mlkjhgfdsq2", "password2": "mlkjhgfdsq2"}
        response = self.client.post(password_change_url_with_hidden_key, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("account_reset_password_from_key_done"))

        # User can log in with his new password.
        self.assertTrue(self.client.login(username=user.email, password="mlkjhgfdsq2"))
        self.client.logout()


class PasswordChangeTest(TestCase):
    def test_password_change_flow(self):
        """
        Ensure that the default allauth account_change_password URL is overridden
        and redirects to the right place.
        """

        user = JobSeekerFactory()
        self.assertTrue(
            self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        )

        # Change password.
        url = reverse("account_change_password")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        post_data = {
            "oldpassword": DEFAULT_PASSWORD,
            "password1": "mlkjhgfdsq2",
            "password2": "mlkjhgfdsq2",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("dashboard:index"))

        # User can log in with his new password.
        self.client.logout()
        self.assertTrue(self.client.login(username=user.email, password="mlkjhgfdsq2"))
        self.client.logout()
