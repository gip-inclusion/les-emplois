from django.core.mail.message import EmailMessage
from factory import Faker

from itou.utils.tasks import AsyncEmailBackend


class TestAsyncEmailBackend:
    def test_send_messages_splits_recipients(self, mailoutbox):
        # 2 emails are needed; one with 50 the other with 25
        recipients = [Faker("email", locale="fr_FR") for _ in range(75)]
        message = EmailMessage(
            from_email="unit-test@tests.com",
            to=recipients,
            subject="subject",
            body="body",
        )

        backend = AsyncEmailBackend()
        # Huey runs in immediate mode.
        sent = backend.send_messages([message])

        assert sent == 2
        [email1, email2] = mailoutbox
        assert len(email1.to) == 50
        assert len(email2.to) == 25
        for email in [email1, email2]:
            assert email.from_email == "unit-test@tests.com"
            assert email.subject == "subject"
            assert email.body == "body"
