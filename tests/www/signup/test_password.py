from allauth.account.forms import default_token_generator
from allauth.account.utils import user_pk_to_url_str
from django.conf import settings
from django.core import mail
from django.urls import reverse
from django.utils.http import urlencode

from tests.users.factories import DEFAULT_PASSWORD, JobSeekerFactory, JobSeekerWithAddressFactory
from tests.utils.test import TestCase


class PasswordResetTest(TestCase):
    def test_password_reset_flow(self):
        user = JobSeekerFactory()

        # Ask for password reset.
        url = reverse("account_reset_password")
        response = self.client.get(url)
        assert response.status_code == 200

        post_data = {"email": user.email}
        response = self.client.post(url, data=post_data)
        args = urlencode({"email": user.email})
        next_url = reverse("account_reset_password_done")
        self.assertRedirects(response, f"{next_url}?{args}")

        # Check sent email.
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert "Réinitialisation de votre mot de passe" in email.subject
        assert (
            "Si vous n'avez pas demandé la réinitialisation de votre mot de passe, vous pouvez ignorer ce message"
            in email.body
        )
        assert email.from_email == settings.DEFAULT_FROM_EMAIL
        assert len(email.to) == 1
        assert email.to[0] == user.email

        # Change forgotten password.
        uidb36 = user_pk_to_url_str(user)
        key = default_token_generator.make_token(user)
        password_change_url = reverse("account_reset_password_from_key", kwargs={"uidb36": uidb36, "key": key})
        response = self.client.get(password_change_url)
        password_change_url_with_hidden_key = response.url
        post_data = {"password1": DEFAULT_PASSWORD, "password2": DEFAULT_PASSWORD}
        response = self.client.post(password_change_url_with_hidden_key, data=post_data)
        self.assertRedirects(response, reverse("account_reset_password_from_key_done"))

        # User can log in with his new password.
        assert self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        self.client.logout()

    def test_password_reset_with_nonexistent_email(self):
        """
        Avoid user enumeration: redirect to the success page even with a nonexistent email.
        """
        url = reverse("account_reset_password")
        response = self.client.get(url)
        assert response.status_code == 200
        post_data = {"email": "nonexistent@email.com"}
        response = self.client.post(url, data=post_data)
        args = urlencode({"email": post_data["email"]})
        next_url = reverse("account_reset_password_done")
        assert response.url == f"{next_url}?{args}"


class PasswordChangeTest(TestCase):
    def test_password_change_flow(self):
        """
        Ensure that the default allauth account_change_password URL is overridden
        and redirects to the right place.
        """

        user = JobSeekerWithAddressFactory()
        self.client.force_login(user)

        # Change password.
        url = reverse("account_change_password")
        response = self.client.get(url)
        assert response.status_code == 200
        new_password = "Mlkjhgf!sq2a"
        post_data = {"oldpassword": DEFAULT_PASSWORD, "password1": new_password, "password2": new_password}
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302
        self.assertRedirects(response, reverse("dashboard:index"))

        # User can log in with his new password.
        self.client.logout()
        assert self.client.login(username=user.email, password=new_password)
