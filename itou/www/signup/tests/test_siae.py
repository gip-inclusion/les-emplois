import uuid
from unittest import mock

from allauth.account.models import EmailConfirmationHMAC
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from itou.siaes.factories import SiaeFactory
from itou.siaes.models import Siae
from itou.users.factories import DEFAULT_PASSWORD
from itou.users.models import User


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

        siae = SiaeFactory(kind=Siae.KIND_ETTI)
        self.assertEqual(0, siae.members.count())

        token = siae.get_token()
        with mock.patch("itou.utils.tokens.SiaeSignupTokenGenerator.make_token", return_value=token):

            url = reverse("signup:siae_select")
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)

            # Find an SIAE by SIREN.
            response = self.client.get(url, {"siren": siae.siret[:9]})
            self.assertEqual(response.status_code, 200)

            # Choose an SIAE between results.
            post_data = {"siaes": siae.pk}
            # Pass `siren` in request.GET
            response = self.client.post(f"{url}?siren={siae.siret[:9]}", data=post_data)
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
            url = siae.signup_magic_link
            post_data = {
                # Hidden fields
                "encoded_siae_id": siae.get_encoded_siae_id(),
                "token": siae.get_token(),
                # Readonly fields
                "siret": siae.siret,
                "kind": siae.kind,
                "siae_name": siae.display_name,
                # Regular fields
                "first_name": user_first_name,
                "last_name": "Doe",
                "email": user_secondary_email,
                "password1": DEFAULT_PASSWORD,
                "password2": DEFAULT_PASSWORD,
            }
            response = self.client.post(url, data=post_data)
            self.assertEqual(response.status_code, 302)
            self.assertRedirects(response, reverse("account_email_verification_sent"))

            self.assertFalse(User.objects.filter(email=user_email).exists())
            user = User.objects.get(email=user_secondary_email)

            # Check `User` state.
            self.assertFalse(user.is_job_seeker)
            self.assertFalse(user.is_prescriber)
            self.assertTrue(user.is_siae_staff)
            self.assertTrue(user.is_active)
            self.assertTrue(siae.has_admin(user))
            self.assertEqual(1, siae.members.count())
            # `username` should be a valid UUID, see `User.generate_unique_username()`.
            self.assertEqual(user.username, uuid.UUID(user.username, version=4).hex)
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
            self.assertIn("Confirmez votre adresse e-mail", subjects)

            # Magic link is no longer valid because siae.members.count() has changed.
            response = self.client.get(magic_link, follow=True)
            redirect_url, status_code = response.redirect_chain[-1]
            self.assertEqual(status_code, 302)
            next_url = reverse("signup:siae_select")
            self.assertEqual(redirect_url, next_url)
            self.assertEqual(response.status_code, 200)
            expected_message = (
                "Ce lien d'inscription est invalide ou a expiré. " "Veuillez procéder à une nouvelle inscription."
            )
            self.assertContains(response, escape(expected_message))

            # User cannot log in until confirmation.
            post_data = {"login": user.email, "password": DEFAULT_PASSWORD}
            url = reverse("account_login")
            response = self.client.post(url, data=post_data)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse("account_email_verification_sent"))

            # Confirm email + auto login.
            confirmation_token = EmailConfirmationHMAC(user_email).key
            confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
            response = self.client.post(confirm_email_url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse("welcoming_tour:index"))
            user_email = user.emailaddress_set.first()
            self.assertTrue(user_email.verified)
