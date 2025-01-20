from datetime import timedelta

from allauth.account.models import EmailConfirmationHMAC
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.emails.models import Email
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

    def test_rate_limiting(self, client, mailoutbox):
        # A user is limited in how many emails they can trigger in one day
        user = JobSeekerFactory(with_unverified_email=True)
        user_email = user.emailaddress_set.first()
        with freeze_time("2023-01-01"):
            confirmation_token = EmailConfirmationHMAC(user_email).key
        url = reverse("account_resend_confirmation_email", kwargs={"key": confirmation_token})

        email_limit = settings.ACCOUNT_MAX_DAILY_EMAIL_CONFIRMATION_REQUESTS
        confirmation_subject_query = "confirmez votre adresse e-mail"

        for i in range(email_limit):
            response = client.get(url)
            assertRedirects(response, reverse("account_email_verification_sent"))
            assert len(mailoutbox) == i + 1
            assert (
                Email.objects.filter(
                    to__contains=[user_email.email],
                    subject__icontains=confirmation_subject_query,
                ).count()
                == i + 1
            )

        response = client.get(url)
        assertRedirects(response, reverse("account_email_rate_limit_exceeded"))
        assert len(mailoutbox) == email_limit
        assert (
            Email.objects.filter(
                to__contains=[user_email.email],
                subject__icontains=confirmation_subject_query,
            ).count()
            == email_limit
        )

        with freeze_time(timezone.now() + timedelta(days=1)):
            response = client.get(url)
            assertRedirects(response, reverse("account_email_verification_sent"))
            assert len(mailoutbox) == email_limit + 1
            assert (
                Email.objects.filter(
                    to__contains=[user_email.email],
                    subject__icontains=confirmation_subject_query,
                ).count()
                == email_limit + 1
            )
