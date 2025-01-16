from allauth.account.models import EmailConfirmationHMAC
from django.conf import settings
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from tests.users.factories import JobSeekerFactory


class TestResendConfirmationView:
    def test_reconfirm_email_address_after_expiry(self, client, mailoutbox):
        # I registered for the service and was sent an email confirmation, but the confirmation expired.
        user = JobSeekerFactory(with_unverified_email=True)
        user_email = user.emailaddress_set.first()
        assert not user_email.verified

        with freeze_time("2023-01-01"):
            confirmation_token = EmailConfirmationHMAC(user_email).key

        # When I try to follow the link to confirm my email, I will be told it's invalid.
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
        response = client.get(confirm_email_url)
        resend_confirmation_url = reverse("account_resend_confirmation_email", kwargs={"key": confirmation_token})
        assertContains(response, resend_confirmation_url)

        # I can request a new confirmation mail.
        response = client.get(resend_confirmation_url)
        assertRedirects(response, reverse("account_email_verification_sent"))
        assert len(mailoutbox) == 1
        email = mailoutbox[0]
        assert "Confirmez votre adresse e-mail" in email.subject
        assert "Afin de finaliser votre inscription, cliquez sur le lien suivant" in email.body
        assert email.from_email == settings.DEFAULT_FROM_EMAIL
        assert len(email.to) == 1
        assert email.to[0] == user.email

        # I can validate my email with a new token.
        confirmation_token = EmailConfirmationHMAC(user_email).key
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
        # NOTE: django-allauth relies on session to perform login during confirmation
        # since I do not have a session, I am not logged in
        response = client.get(confirm_email_url)
        assertRedirects(response, reverse("account_login"))
        user_email = user.emailaddress_set.first()
        assert user_email.verified

        # Once the email is validated, I cannot request new emails.
        count_emails_sent = len(mailoutbox)
        response = client.get(resend_confirmation_url)
        assert len(mailoutbox) == count_emails_sent

    def test_cannot_reconfirm_email_address_invalid_token(self, client):
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": "something-invalid"})
        response = client.get(confirm_email_url)
        resend_confirmation_url = reverse("account_resend_confirmation_email", kwargs={"key": "something-invalid"})
        assertNotContains(response, resend_confirmation_url)

        response = client.get(resend_confirmation_url)
        assertRedirects(response, reverse("signup:choose_user_kind"))
