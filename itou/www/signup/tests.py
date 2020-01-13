from allauth.account.forms import default_token_generator
from allauth.account.utils import user_pk_to_url_str

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape
from django.utils.translation import gettext_lazy as _

from itou.prescribers.factories import PrescriberOrganizationFactory
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory

from itou.siaes.factories import SiaeFactory, SiaeWithMembershipFactory
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


class SiaeSignupTest(TestCase):
    def test_siae_signup_story_of_jacques(self):
        """
        Test the following SIAE signup case:
        - email does not match any siae
        - siret matches two siaes
        - (siret, kind) matches one siae
        - existing siae has no user yet
        Story and expected results:
        - user is created but inactive
        - email with magic link is sent to siae.email
        - user sees account_inactive page when trying to login
        - user cannot signup again with same email
        - siae.email opens magic link to validate user
        - second use of magic link shows "this link has already been used"
        - user is now active and can login
        - itou staff manually disables the user
        - user sees account_inactive page when trying to login
        - magic link cannot be reused to reactivate the user
        """
        user_first_name = "Jacques"
        user_email = "jacques.doe@siae.com"

        siae1 = SiaeFactory()
        siae1.kind = Siae.KIND_ETTI
        siae1.save()

        siae2 = SiaeFactory()
        siae2.kind = Siae.KIND_ACI
        siae2.siret = siae1.siret
        siae2.save()

        url = reverse("signup:siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        signup_post_data = {
            "first_name": user_first_name,
            "last_name": "Doe",
            "email": user_email,
            "siret": siae1.siret,
            "kind": siae1.kind,
            "password1": "!*p4ssw0rd123-",
            "password2": "!*p4ssw0rd123-",
        }

        post_data = signup_post_data
        response = self.client.post(url, data=post_data, follow=True)
        redirect_url, status_code = response.redirect_chain[-1]
        self.assertEqual(status_code, 302)
        new_user = get_user_model().objects.get(email=user_email)
        next_url = reverse(
            "signup:account_inactive", kwargs={"user_uuid": new_user.uuid}
        )
        self.assertEqual(redirect_url, next_url)
        self.assertEqual(response.status_code, 200)
        expected_message = _("Ce compte est inactif et en attente de validation.")
        self.assertContains(response, escape(expected_message))

        self.assertFalse(new_user.is_job_seeker)
        self.assertFalse(new_user.is_prescriber)
        self.assertTrue(new_user.is_siae_staff)
        self.assertFalse(new_user.is_active)
        self.assertTrue(new_user.has_pending_validation)

        siae1 = Siae.active_objects.get(
            siret=post_data["siret"], kind=post_data["kind"]
        )
        self.assertTrue(new_user.siaemembership_set.get(siae=siae1).is_siae_admin)
        self.assertEqual(1, siae1.members.count())

        # siae2 is left untouched even though it has the same siret as siae1.
        siae2 = Siae.active_objects.get(siret=siae2.siret, kind=siae2.kind)
        self.assertEqual(0, siae2.members.count())

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn(
            "Un nouvel utilisateur souhaite rejoindre votre structure", email.subject
        )
        self.assertIn(
            "Pour valider l'activation de ce nouvel utilisateur, ouvrez ce lien",
            email.body,
        )
        magic_link = new_user.uservalidation.get_magic_link()
        self.assertIn(magic_link, email.body)
        self.assertIn(new_user.first_name, email.body)
        self.assertIn(new_user.last_name, email.body)
        self.assertIn(new_user.email, email.body)
        self.assertIn(siae1.display_name, email.body)
        self.assertIn(siae1.siret, email.body)
        self.assertIn(siae1.kind, email.body)
        self.assertIn(siae1.email, email.body)
        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(email.to[0], siae1.email)

        url = reverse("account_login")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {"login": user_email, "password": "!*p4ssw0rd123-"}
        response = self.client.post(url, data=post_data, follow=True)
        redirect_url, status_code = response.redirect_chain[-1]
        self.assertEqual(status_code, 302)
        next_url = reverse(
            "signup:account_inactive", kwargs={"user_uuid": new_user.uuid}
        )
        self.assertEqual(redirect_url, next_url)
        self.assertEqual(response.status_code, 200)
        expected_message = _("Ce compte est inactif et en attente de validation.")
        self.assertContains(response, escape(expected_message))

        url = reverse("signup:siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = signup_post_data
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Un autre utilisateur utilise déjà cette adresse e-mail."
        )

        new_user.refresh_from_db()
        self.assertFalse(new_user.is_active)
        self.assertFalse(new_user.uservalidation.is_validated)
        self.assertTrue(new_user.has_pending_validation)

        url = magic_link
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        expected_message = _(
            f"L'utilisateur {new_user.email} a bien été validé "
            f"et peut maintenant s'identifier sur la plateforme."
        )
        self.assertContains(response, escape(expected_message))

        new_user.refresh_from_db()
        self.assertTrue(new_user.is_active)
        self.assertTrue(new_user.uservalidation.is_validated)
        self.assertFalse(new_user.has_pending_validation)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        expected_message = _(
            f"Ce lien d'activation du compte {new_user.email} a déjà été utilisé."
        )
        self.assertContains(response, escape(expected_message))

        url = reverse("account_login")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {"login": user_email, "password": "!*p4ssw0rd123-"}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        next_url = reverse("dashboard:index")
        self.assertEqual(response.url, next_url)

        new_user.is_active = False
        new_user.save()

        url = reverse("account_login")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {"login": user_email, "password": "!*p4ssw0rd123-"}
        response = self.client.post(url, data=post_data, follow=True)
        redirect_url, status_code = response.redirect_chain[-1]
        self.assertEqual(status_code, 302)
        next_url = reverse(
            "signup:account_inactive", kwargs={"user_uuid": new_user.uuid}
        )
        self.assertEqual(redirect_url, next_url)
        self.assertEqual(response.status_code, 200)
        expected_message = _(
            "Ce compte est inactif car il a été manuellement désactivé"
        )
        self.assertContains(response, escape(expected_message))

        url = magic_link
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        url = reverse("account_login")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {"login": user_email, "password": "!*p4ssw0rd123-"}
        response = self.client.post(url, data=post_data, follow=True)
        redirect_url, status_code = response.redirect_chain[-1]
        self.assertEqual(status_code, 302)
        next_url = reverse(
            "signup:account_inactive", kwargs={"user_uuid": new_user.uuid}
        )
        self.assertEqual(redirect_url, next_url)
        self.assertEqual(response.status_code, 200)
        expected_message = _(
            "Ce compte est inactif car il a été manuellement désactivé"
        )
        self.assertContains(response, escape(expected_message))

    def test_siae_signup_story_of_jessica(self):
        """
        Test the following SIAE signup case:
        - email does not match any siae
        - siret matches two siaes
        - (siret, kind) matches one siae
        - existing siae already has an (admin) user
        Story and expected results:
        - new user is created and active
        - a warning fyi-only email is sent to the admin user
        - new user can login and access dashboard
        """
        user_first_name = "Jessica"
        user_email = "jessica.doe@siae.com"

        siae1 = SiaeWithMembershipFactory()
        siae1.kind = Siae.KIND_ETTI
        siae1.save()

        self.assertEqual(len(siae1.active_admin_members), 1)
        existing_admin_user = siae1.active_admin_members[0]

        siae2 = SiaeFactory()
        siae2.kind = Siae.KIND_ACI
        siae2.siret = siae1.siret
        siae2.save()

        url = reverse("signup:siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "first_name": user_first_name,
            "last_name": "Doe",
            "email": user_email,
            "siret": siae1.siret,
            "kind": siae1.kind,
            "password1": "!*p4ssw0rd123-",
            "password2": "!*p4ssw0rd123-",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        next_url = reverse("dashboard:index")
        self.assertEqual(response.url, next_url)

        new_user = get_user_model().objects.get(email=post_data["email"])
        self.assertFalse(new_user.is_job_seeker)
        self.assertFalse(new_user.is_prescriber)
        self.assertTrue(new_user.is_siae_staff)
        self.assertTrue(new_user.is_active)
        self.assertFalse(new_user.has_pending_validation)

        siae1 = Siae.active_objects.get(
            siret=post_data["siret"], kind=post_data["kind"]
        )
        self.assertFalse(new_user.siaemembership_set.get(siae=siae1).is_siae_admin)
        self.assertEqual(2, siae1.members.count())

        # siae2 is left untouched even though it has the same siret as siae1.
        siae2 = Siae.active_objects.get(siret=siae2.siret, kind=siae2.kind)
        self.assertEqual(0, siae2.members.count())

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn(
            "Un nouvel utilisateur vient de rejoindre votre structure", email.subject
        )
        self.assertIn(
            "Si vous ne connaissez pas cette personne veuillez nous contacter",
            email.body,
        )
        self.assertIn(new_user.first_name, email.body)
        self.assertIn(new_user.last_name, email.body)
        self.assertIn(new_user.email, email.body)
        self.assertIn(siae1.display_name, email.body)
        self.assertIn(siae1.siret, email.body)
        self.assertIn(siae1.kind, email.body)
        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(email.to[0], existing_admin_user.email)

        self.client.logout()

        url = reverse("account_login")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {"login": user_email, "password": "!*p4ssw0rd123-"}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        next_url = reverse("dashboard:index")
        self.assertEqual(response.url, next_url)

    def test_siae_signup_story_of_brian(self):
        """
        Test the following SIAE signup case:
        - email does not match any siae
        - siret matches one siae
        - existing siae has no user yet
        Story and expected results:
        - user1 signs up
        - user1 is created but inactive (and never activated)
        - first magic link is sent
        - user2 signs up with same siret but different email
        - user2 is created and admin but inactive
        - a different magic link is sent
        """
        user_first_name = "Brian"
        user_email1 = "brian.doe@siae.com"
        user_email2 = "brian.doe@hotmail.com"

        siae = SiaeFactory()
        siae.save()

        url = reverse("signup:siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        signup_post_data = {
            "first_name": user_first_name,
            "last_name": "Doe",
            "email": user_email1,
            "siret": siae.siret,
            "kind": siae.kind,
            "password1": "!*p4ssw0rd123-",
            "password2": "!*p4ssw0rd123-",
        }

        post_data = signup_post_data
        response = self.client.post(url, data=post_data, follow=True)
        redirect_url, status_code = response.redirect_chain[-1]
        self.assertEqual(status_code, 302)
        new_user1 = get_user_model().objects.get(email=user_email1)
        next_url = reverse(
            "signup:account_inactive", kwargs={"user_uuid": new_user1.uuid}
        )
        self.assertEqual(redirect_url, next_url)
        self.assertEqual(response.status_code, 200)
        expected_message = _("Ce compte est inactif et en attente de validation.")
        self.assertContains(response, escape(expected_message))

        self.assertFalse(new_user1.is_active)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn(
            "Un nouvel utilisateur souhaite rejoindre votre structure", email.subject
        )
        magic_link1 = new_user1.uservalidation.get_magic_link()
        self.assertIn(magic_link1, email.body)
        self.assertIn(user_email1, email.body)

        post_data = signup_post_data
        post_data["email"] = user_email2
        response = self.client.post(url, data=post_data, follow=True)
        redirect_url, status_code = response.redirect_chain[-1]
        self.assertEqual(status_code, 302)
        new_user2 = get_user_model().objects.get(email=user_email2)
        next_url = reverse(
            "signup:account_inactive", kwargs={"user_uuid": new_user2.uuid}
        )
        self.assertEqual(redirect_url, next_url)
        self.assertEqual(response.status_code, 200)
        expected_message = _("Ce compte est inactif et en attente de validation.")
        self.assertContains(response, escape(expected_message))

        self.assertFalse(new_user2.is_active)

        siae = Siae.active_objects.get(siret=siae.siret)
        self.assertTrue(new_user2.is_admin_of_siae(siae))

        self.assertEqual(len(mail.outbox), 2)
        email = mail.outbox[1]
        self.assertIn(
            "Un nouvel utilisateur souhaite rejoindre votre structure", email.subject
        )
        magic_link2 = new_user2.uservalidation.get_magic_link()
        self.assertIn(magic_link2, email.body)
        self.assertIn(user_email2, email.body)

        self.assertNotEqual(magic_link1, magic_link2)

    def test_siae_signup_story_of_pascal(self):
        """
        Test the following SIAE signup case:
        - email does not match any siae
        - siret matches one siae
        - existing siae has no user yet
        Story and expected results:
        - user is created but inactive
        - user sees account_inactive page when trying to login
        - user cannot signup again with same email
        - user deletes itself from the account_inactive page
        - user can signup again with same email
        """
        user_first_name = "Pascal"
        user_email = "pascal.doe@siae.com"

        siae = SiaeFactory()
        siae.save()

        url = reverse("signup:siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        signup_post_data = {
            "first_name": user_first_name,
            "last_name": "Doe",
            "email": user_email,
            "siret": siae.siret,
            "kind": siae.kind,
            "password1": "!*p4ssw0rd123-",
            "password2": "!*p4ssw0rd123-",
        }

        post_data = signup_post_data
        response = self.client.post(url, data=post_data, follow=True)
        redirect_url, status_code = response.redirect_chain[-1]
        self.assertEqual(status_code, 302)
        new_user = get_user_model().objects.get(email=user_email)
        next_url = reverse(
            "signup:account_inactive", kwargs={"user_uuid": new_user.uuid}
        )
        self.assertEqual(redirect_url, next_url)
        self.assertEqual(response.status_code, 200)
        expected_message = _("Ce compte est inactif et en attente de validation.")
        self.assertContains(response, escape(expected_message))

        post_data = signup_post_data
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response, "Un autre utilisateur utilise déjà cette adresse e-mail."
        )

        # FIXME WIP delete own account

    def test_siae_signup_story_of_daniela(self):
        """
        Test the following SIAE signup case:
        - email does not match any siae
        - siret does not match any siae
        Story and expected results:
        - we show an explanation that a ASP-siret or ASP-email is required
        """
        pass

    def test_siae_signup_story_of_david(self):
        """
        Test the following SIAE signup case:
        - email matches two siaes
        - siret matches one siae
        - existing siae has no user yet
        Story and expected results:
        - user is created but inactive
        - user is associated to siae matching siret
        """
        pass

    def test_siae_signup_story_of_emilie(self):
        """
        Test the following SIAE signup case:
        - email matches two siaes
        - siret does not match any siae
        Story and expected results:
        - we show a message explaining why we could not match a siae
        """
        pass

    def test_siae_signup_story_of_bernadette(self):
        """
        Test the following SIAE signup case:
        - email matches one siae
        - siret does not match any siae
        - existing siae has no user yet
        Story and expected results:
        - user is created but inactive
        - user is associated to siae matching email
        """
        pass

    def test_siae_signup_story_of_leonard(self):
        """
        Test the following SIAE signup case:
        - email matches one siae
        - siret matches one siae (a different one)
        - existing siae has no user yet
        Story and expected results:
        - priority is given to siret match over email match
        - user is created but inactive
        - user is associated to siae matching siret
        """
        pass

    def test_attack_on_user_validation_secret(self):
        """
        Test an attack attempt on a user validation secret
        """
        pass


class JobSeekerSignupTest(TestCase):
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


class UserEmailUniquenessTest(TestCase):
    def test_user_email_uniqueness(self):
        """Test case insensitive uniqueness of user email"""
        email_lowercase = "john.doe@siae.com"
        email_mixedcase = "JoHn.DoE@SiAe.cOm"
        email_uppercase = "JOHN.DOE@SIAE.com"
        email_different = "XoHn.DoE@SiAe.cOm"

        url = reverse("signup:job_seeker")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": email_lowercase,
            "password1": "!*p4ssw0rd123-",
            "password2": "!*p4ssw0rd123-",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:index"))

        user = get_user_model().objects.get(email=post_data["email"])
        self.assertTrue(user.is_job_seeker)
        self.assertFalse(user.is_prescriber)
        self.assertFalse(user.is_siae_staff)

        self.client.logout()

        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": email_lowercase,
            "password1": "!*p4ssw0rd123-",
            "password2": "!*p4ssw0rd123-",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response, "Un autre utilisateur utilise déjà cette adresse e-mail."
        )

        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": email_mixedcase,
            "password1": "!*p4ssw0rd123-",
            "password2": "!*p4ssw0rd123-",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response, "Un autre utilisateur utilise déjà cette adresse e-mail."
        )

        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": email_uppercase,
            "password1": "!*p4ssw0rd123-",
            "password2": "!*p4ssw0rd123-",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response, "Un autre utilisateur utilise déjà cette adresse e-mail."
        )

        post_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": email_different,
            "password1": "!*p4ssw0rd123-",
            "password2": "!*p4ssw0rd123-",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:index"))
