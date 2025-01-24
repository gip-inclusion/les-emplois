from unittest import mock

from django.conf import settings
from django.utils import timezone

from itou.emails.models import EmailAddress, EmailConfirmation
from tests.users.factories import JobSeekerFactory


class TestEmailConfirmation:
    def test_send_confirmation_email(self, snapshot):
        sent_emails = []

        def mock_send_email(self, **kwargs):
            sent_emails.append(self)

        user = JobSeekerFactory()
        email_confirmation = EmailConfirmation.create(EmailAddress.objects.create(user=user, email=user.email))
        with mock.patch("django.core.mail.EmailMessage.send", mock_send_email):
            email_confirmation.send()

        assert len(sent_emails) == 1
        assert sent_emails[0].to == [user.email]
        assert sent_emails[0].subject == snapshot(name="email subject")

        # Get the token from the email for testing
        confirmation_url = email_confirmation.get_confirmation_url(absolute_url=True)
        assert confirmation_url.startswith(f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}/")
        assert sent_emails[0].body.replace(confirmation_url, "[CONFIRMATION URL REMOVED]") == snapshot(
            name="email body"
        )

        email_confirmation.refresh_from_db()
        assert email_confirmation.sent.date() == timezone.localdate()

    def test_send_confirmation_email_signup(self, snapshot):
        sent_emails = []

        def mock_send_email(self, **kwargs):
            sent_emails.append(self)

        user = JobSeekerFactory()
        email_confirmation = EmailConfirmation.create(EmailAddress.objects.create(user=user, email=user.email))
        with mock.patch("django.core.mail.EmailMessage.send", mock_send_email):
            email_confirmation.send(signup=True)

        assert len(sent_emails) == 1
        assert sent_emails[0].to == [user.email]
        assert sent_emails[0].subject == snapshot(name="email subject")

        confirmation_url = email_confirmation.get_confirmation_url(absolute_url=True)
        assert confirmation_url.startswith(f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}/")
        assert sent_emails[0].body.replace(confirmation_url, "[CONFIRMATION URL REMOVED]") == snapshot(
            name="email body"
        )

        email_confirmation.refresh_from_db()
        assert email_confirmation.sent.date() == timezone.localdate()
