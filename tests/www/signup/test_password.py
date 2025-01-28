from unittest import mock

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from freezegun import freeze_time
from pytest_django.asserts import assertMessages, assertRedirects

from itou.utils.tokens import EmailAwarePasswordResetTokenGenerator
from tests.users.factories import DEFAULT_PASSWORD, JobSeekerFactory
from tests.utils.test import parse_response_to_soup


class TestPasswordReset:
    def _get_password_change_from_key_url(self, user):
        uidb36 = user.pk_to_url_str
        key = EmailAwarePasswordResetTokenGenerator().make_token(user)
        return reverse("accounts:account_reset_password_from_key", kwargs={"uidb36": uidb36, "key": key})

    def test_password_reset_flow(self, client, mailoutbox):
        user = JobSeekerFactory(last_login=timezone.now(), password="somethingElse%", with_verified_email=True)

        # Ask for password reset.
        url = reverse("accounts:account_reset_password")
        response = client.get(url)
        assert response.status_code == 200

        post_data = {"email": user.email}
        response = client.post(url, data=post_data)
        args = urlencode({"email": user.email})
        next_url = reverse("accounts:account_reset_password_done")
        assertRedirects(response, f"{next_url}?{args}")

        # Check sent email.
        assert len(mailoutbox) == 1
        email = mailoutbox[0]
        assert "Réinitialisation de votre mot de passe" in email.subject
        assert (
            "Si vous n'avez pas demandé la réinitialisation de votre mot de passe, vous pouvez ignorer ce message"
            in email.body
        )
        assert email.from_email == settings.DEFAULT_FROM_EMAIL
        assert len(email.to) == 1
        assert email.to[0] == user.email

        # Change forgotten password.
        password_change_url = self._get_password_change_from_key_url(user)
        response = client.get(password_change_url)
        password_change_url_with_hidden_key = response.url
        post_data = {"password1": DEFAULT_PASSWORD, "password2": DEFAULT_PASSWORD}
        response = client.post(password_change_url_with_hidden_key, data=post_data)
        assertRedirects(response, reverse("accounts:account_reset_password_from_key_done"))

        # User can log in with their new password.
        assert client.login(username=user.email, password=DEFAULT_PASSWORD)
        client.logout()

    def test_password_reset_with_nonexistent_email(self, client, mailoutbox, snapshot):
        """
        Avoid user enumeration: redirect to the success page even with a nonexistent email.
        """
        url = reverse("accounts:account_reset_password")
        response = client.get(url)
        assert response.status_code == 200
        post_data = {"email": "nonexistent@email.com"}
        response = client.post(url, data=post_data)
        args = urlencode({"email": post_data["email"]})
        next_url = reverse("accounts:account_reset_password_done")
        assertRedirects(response, f"{next_url}?{args}")

        assert len(mailoutbox) == 1
        email = mailoutbox[0]
        assert email.subject == snapshot(name="email subject")
        assert email.body == snapshot(name="email body")
        assert email.from_email == settings.DEFAULT_FROM_EMAIL
        assert len(email.to) == 1
        assert email.to[0] == post_data["email"]

    def test_password_reset_user_creation(self, client, snapshot):
        # user creation differs because they are logged in and redirected to the welcoming tour on creation
        user = JobSeekerFactory(last_login=None)

        password_change_url = self._get_password_change_from_key_url(user)
        response = client.get(password_change_url)
        password_change_url_with_hidden_key = response.url

        response = client.get(password_change_url_with_hidden_key)
        assert (
            str(
                parse_response_to_soup(
                    response,
                    "#main",
                    replace_in_attr=[
                        (
                            "action",
                            password_change_url_with_hidden_key,
                            "[change password form url]",
                        )
                    ],
                )
            )
            == snapshot
        )

        post_data = {"password1": DEFAULT_PASSWORD, "password2": DEFAULT_PASSWORD}
        response = client.post(password_change_url_with_hidden_key, data=post_data)
        assertRedirects(response, reverse("welcoming_tour:index"))
        assert get_user(client).is_authenticated is True

        # User can log in with their new password.
        client.logout()
        assert client.login(username=user.email, password=DEFAULT_PASSWORD)

    def test_password_reset_token_invalid_content(self, client, snapshot):
        # user creation differs because they are logged in and redirected to the welcoming tour on creation
        password_change_url = reverse(
            "accounts:account_reset_password_from_key", kwargs={"uidb36": "something", "key": "invalid"}
        )
        response = client.get(password_change_url)
        assert str(parse_response_to_soup(response, "#main")) == snapshot


class TestPasswordChange:
    @freeze_time("2023-08-31 12:34:56")
    def test_password_change_flow(self, client, snapshot):
        """
        Ensure that the default allauth account_change_password URL is overridden
        and redirects to the right place.
        """

        sent_emails = []

        def mock_send_email(self, **kwargs):
            sent_emails.append(self)

        user = JobSeekerFactory(with_address=True)
        client.force_login(user)

        # Change password.
        url = reverse("accounts:account_change_password")
        response = client.get(url)
        assert response.status_code == 200
        new_password = "Mlkjhgf!sq2a'4"
        post_data = {"oldpassword": DEFAULT_PASSWORD, "password1": new_password, "password2": new_password}
        with mock.patch("django.core.mail.EmailMessage.send", mock_send_email):
            response = client.post(url, data=post_data)
        assertRedirects(response, reverse("dashboard:index"))

        # User is notified of confirmation in-site and by email.
        assertMessages(response, [messages.Message(messages.SUCCESS, "Mot de passe modifié avec succès.")])
        assert len(sent_emails) == 1
        assert sent_emails[0].to == [user.email]
        assert sent_emails[0].subject == snapshot(name="email subject")
        assert sent_emails[0].body == snapshot(name="email body")

        # User is not logged out.
        assert get_user(client).is_authenticated is True

        # User can log in with their new password.
        client.logout()
        assert client.login(username=user.email, password=new_password)
