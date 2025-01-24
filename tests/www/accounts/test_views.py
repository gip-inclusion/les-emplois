from unittest import mock

from django.contrib import messages
from django.contrib.auth import get_user
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertNotContains

from itou.emails.models import EmailAddress, EmailConfirmation
from tests.users.factories import JobSeekerFactory
from tests.utils.tests import parse_response_to_soup


class TestAccountInactiveView:
    def test_inactive_account(self, client):
        pass


class TestEmailVerificationSentView:
    def test_page_content(self, client, snapshot):
        response = client.get(reverse("accounts:account_email_verification_sent"))
        assert str(parse_response_to_soup(response, selector="#main")) == snapshot


class TestConfirmEmailView:
    def test_confirm_email(self, client):
        # TODO: replace with factory trait with_unverified_email from https://github.com/gip-inclusion/les-emplois/pull/5428
        user = JobSeekerFactory()
        confirm_email_url = EmailConfirmation.create(
            EmailAddress.objects.create(user=user, email=user.email)
        ).get_confirmation_url()

        response = client.get(confirm_email_url)
        assertContains(response, user.email)
        # Soup will raise error if there is no form for POSTing confirmation.
        parse_response_to_soup(response, selector=f"form[action='{confirm_email_url}']")

        # NOTE: Redirect logic is covered by other tests.
        response = client.post(confirm_email_url, {})
        assert get_user(client).is_authenticated
        assertMessages(response, [messages.Message(messages.SUCCESS, f"Vous avez confirmé {user.email}")])

        email_address = EmailAddress.objects.get(user=user)
        assert email_address.verified
        assert email_address.primary

        confirmation = EmailConfirmation.objects.get(email_address=email_address)
        assert confirmation.used
        assert not confirmation.can_confirm_email()

    @freeze_time("2023-08-31 12:34:56")
    def test_confirm_changed_email(self, client, snapshot):
        # I confirm an email when I already have another email associated with my account
        sent_emails = []

        def mock_send_email(self, **kwargs):
            sent_emails.append(self)

        user = JobSeekerFactory(for_snapshot=True, with_verified_email=True)
        new_email = "newemail@test.org"
        old_email = user.email
        with mock.patch("django.core.mail.EmailMessage.send", mock_send_email):
            new_email_address = user.email_addresses.add_new_email(user, new_email, send_confirmation=True)
            assert not new_email_address.verified
            assert not new_email_address.primary

            # Email not changed until it is verified.
            user.refresh_from_db()
            assert user.email == old_email
            assert user.email_addresses.count() == 2

            assert len(sent_emails) == 1  # Confirmation email.
            email_confirmation = EmailConfirmation.objects.get(email_address=new_email_address)
            assert email_confirmation.can_confirm_email()

            # Simulate request and confirmation.
            response = client.post(email_confirmation.get_confirmation_url(), {})
            assert get_user(client).is_authenticated
            assertMessages(response, [messages.Message(messages.SUCCESS, f"Vous avez confirmé {new_email}")])

            email_confirmation.refresh_from_db()
            assert email_confirmation.used

            # Received a notification that email has changed.
            assert len(sent_emails) == 2
            assert sent_emails[1].to == [new_email]
            assert sent_emails[1].subject == snapshot(name="email subject")
            assert sent_emails[1].body == snapshot(name="email body")

            # User e-mail has been replaced.
            new_email_address.refresh_from_db()
            assert new_email_address.verified
            assert new_email_address.primary

            user.refresh_from_db()
            assert user.email == new_email

            # Old email has been released.
            assert user.email_addresses.count() == 1
            assert not EmailAddress.objects.filter(email=old_email).exists()

    def test_logs_out_existing_session(self, client, snapshot):
        """
        A user who is already logged in provides a valid URL. They should be logged out
        """
        client.force_login(JobSeekerFactory())

        new_user = JobSeekerFactory()
        confirm_email_url = EmailConfirmation.create(
            EmailAddress.objects.create(user=new_user, email=new_user.email)
        ).get_confirmation_url()
        client.post(confirm_email_url, {})
        authenticated_user = get_user(client)
        assert authenticated_user.is_authenticated
        assert authenticated_user == new_user

    def test_invalid_url(self, client, snapshot):
        response = client.get(reverse("accounts:account_confirm_email", args=["something-invalid"]))
        assert str(parse_response_to_soup(response, selector="#main")) == snapshot

    # TODO: is this test necessary? If the user has already used the link, then their email will be verified
    # Instead add tests on the model regarding the protections surrounding used.
    def test_used_confirmation(self, client):
        user = JobSeekerFactory()
        confirm_email = EmailConfirmation.create(EmailAddress.objects.create(user=user, email=user.email))
        confirm_email.used = True
        confirm_email.save()

        url = confirm_email.get_confirmation_url()
        response = client.get(url)
        assertNotContains(response, url)
        assert get_user(client).is_authenticated is False

        response = client.post(url)
        assert get_user(client).is_authenticated is False

    def test_confirm_email_verified(self, client):
        # Using a link on an email that's already been verified
        user = JobSeekerFactory()
        email_address = EmailAddress.objects.create(user=user, email=user.email, verified=True)
        confirm_email = EmailConfirmation.create(email_address)

        url = confirm_email.get_confirmation_url()
        response = client.get(url)
        # TODO(calum): Change this test to propose that the user is redirected to ExistingUserLogin.
        assertNotContains(response, url)
        assert get_user(client).is_authenticated is False

        response = client.post(url)
        assert get_user(client).is_authenticated is False


class TestPasswordResetDoneView:
    def test_get(self, client, snapshot):
        response = client.get(reverse("accounts:account_reset_password_done"))
        assert response.status_code == 200
        assert str(parse_response_to_soup(response, selector="#main")) == snapshot
        assertNotContains(response, "vous êtes déjà connecté en tant que")

    def test_already_logged_in(self, client, snapshot):
        # Content is changed if user is authenticated
        client.force_login(JobSeekerFactory(for_snapshot=True))
        response = client.get(reverse("accounts:account_reset_password_done"))
        assert response.status_code == 200
        assert str(parse_response_to_soup(response, selector="#main")) == snapshot
        assertContains(response, "vous êtes déjà connecté en tant que")


class TestPasswordResetFromKeyDoneView:
    def test_get(self, client, snapshot):
        response = client.get(reverse("accounts:account_reset_password_from_key_done"))
        assert response.status_code == 200
        assert str(parse_response_to_soup(response, selector="#main")) == snapshot
