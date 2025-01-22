from django.contrib import messages
from django.contrib.auth import get_user
from django.urls import reverse
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
