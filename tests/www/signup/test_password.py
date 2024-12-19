from allauth.account.forms import default_token_generator
from allauth.account.utils import user_pk_to_url_str
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from pytest_django.asserts import assertRedirects

from tests.users.factories import DEFAULT_PASSWORD, JobSeekerFactory
from tests.utils.test import parse_response_to_soup


class TestPasswordReset:
    def _get_password_change_from_key_url(self, user):
        uidb36 = user_pk_to_url_str(user)
        key = default_token_generator.make_token(user)
        return reverse("account_reset_password_from_key", kwargs={"uidb36": uidb36, "key": key})

    def test_password_reset_flow(self, client, mailoutbox):
        user = JobSeekerFactory(last_login=timezone.now(), password="somethingElse%")

        # Ask for password reset.
        url = reverse("account_reset_password")
        response = client.get(url)
        assert response.status_code == 200

        post_data = {"email": user.email}
        response = client.post(url, data=post_data)
        args = urlencode({"email": user.email})
        next_url = reverse("account_reset_password_done")
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
        assertRedirects(response, reverse("account_reset_password_from_key_done"))

        # User can log in with their new password.
        assert client.login(username=user.email, password=DEFAULT_PASSWORD)
        client.logout()

    def test_password_reset_with_nonexistent_email(self, client):
        """
        Avoid user enumeration: redirect to the success page even with a nonexistent email.
        """
        url = reverse("account_reset_password")
        response = client.get(url)
        assert response.status_code == 200
        post_data = {"email": "nonexistent@email.com"}
        response = client.post(url, data=post_data)
        args = urlencode({"email": post_data["email"]})
        next_url = reverse("account_reset_password_done")
        assert response.url == f"{next_url}?{args}"

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
        assert response.context["request"].user.is_authenticated

        # User can log in with their new password.
        client.logout()
        assert client.login(username=user.email, password=DEFAULT_PASSWORD)

    def test_password_reset_token_invalid_content(self, client, snapshot):
        # user creation differs because they are logged in and redirected to the welcoming tour on creation
        password_change_url = reverse(
            "account_reset_password_from_key", kwargs={"uidb36": "something", "key": "invalid"}
        )
        response = client.get(password_change_url)
        assert str(parse_response_to_soup(response, "#main")) == snapshot


class TestPasswordChange:
    def test_password_change_flow(self, client):
        """
        Ensure that the default allauth account_change_password URL is overridden
        and redirects to the right place.
        """

        user = JobSeekerFactory(with_address=True)
        client.force_login(user)

        # Change password.
        url = reverse("account_change_password")
        response = client.get(url)
        assert response.status_code == 200
        new_password = "Mlkjhgf!sq2a'4"
        post_data = {"oldpassword": DEFAULT_PASSWORD, "password1": new_password, "password2": new_password}
        response = client.post(url, data=post_data)
        assert response.status_code == 302
        assertRedirects(response, reverse("dashboard:index"))

        # User can log in with their new password.
        client.logout()
        assert client.login(username=user.email, password=new_password)
