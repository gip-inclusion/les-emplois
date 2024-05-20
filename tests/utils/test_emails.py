from django.core.mail.message import EmailMessage
from factory import Faker

from itou.utils.tasks import sanitize_mailjet_recipients
from tests.utils.test import TestCase


class UtilsEmailsSplitRecipientTest(TestCase):
    """
    Test behavior of email backend when sending emails with more than 50 recipients
    (Mailjet API Limit)
    """

    def test_email_copy(self):
        fake_email = Faker("email", locale="fr_FR")
        message = EmailMessage(from_email="unit-test@tests.com", body="xxx", to=[fake_email], subject="test")
        result = sanitize_mailjet_recipients(message)

        assert 1 == len(result)

        assert "xxx" == result[0].body
        assert "unit-test@tests.com" == result[0].from_email
        assert fake_email == result[0].to[0]
        assert "test" == result[0].subject

    def test_dont_split_emails(self):
        recipients = []
        # Only one email is needed
        for _ in range(49):
            recipients.append(Faker("email", locale="fr_FR"))

        message = EmailMessage(from_email="unit-test@tests.com", body="", to=recipients)
        result = sanitize_mailjet_recipients(message)

        assert 1 == len(result)
        assert 49 == len(result[0].to)

    def test_must_split_emails(self):
        # 2 emails are needed; one with 50 the other with 25
        recipients = []
        for _ in range(75):
            recipients.append(Faker("email", locale="fr_FR"))

        message = EmailMessage(from_email="unit-test@tests.com", body="", to=recipients)
        result = sanitize_mailjet_recipients(message)

        assert 2 == len(result)
        assert 50 == len(result[0].to)
        assert 25 == len(result[1].to)
