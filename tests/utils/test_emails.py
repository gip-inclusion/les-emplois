import pytest
from django.core.mail.message import EmailMessage
from factory import Faker

from itou.utils.tasks import AsyncEmailBackend, _async_send_message


class TestAsyncEmailBackend:
    def test_send_messages_splits_recipients(self, django_capture_on_commit_callbacks, mailoutbox):
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
        with django_capture_on_commit_callbacks(execute=True):
            sent = backend.send_messages([message])

        assert sent == 2
        [email1, email2] = mailoutbox
        assert len(email1.to) == 50
        assert len(email2.to) == 25
        for email in [email1, email2]:
            assert email.from_email == "unit-test@tests.com"
            assert email.subject == "subject"
            assert email.body == "body"


@pytest.fixture
def anymail_mailjet_settings(settings):
    settings.ASYNC_EMAIL_BACKEND = "anymail.backends.mailjet.EmailBackend"
    settings.ANYMAIL = {
        "MAILJET_API_URL": settings.ANYMAIL["MAILJET_API_URL"],
        "MAILJET_API_KEY": "MAILJET_API_SECRET",
        "MAILJET_SECRET_KEY": "MAILJET_SECRET_KEY",
    }
    return settings


class TestAsyncSendMessage:
    EXC_TEXT = "Exception: Huey, please retry this task."

    def test_send_ok(self, anymail_mailjet_settings, caplog, requests_mock):
        requests_mock.post(
            f"{anymail_mailjet_settings.ANYMAIL['MAILJET_API_URL']}send",
            # https://dev.mailjet.com/email/guides/send-api-v31/#send-in-bulk
            json={
                "Messages": [
                    {
                        "Status": "success",
                        "To": [
                            {
                                "Email": "passenger2@mailjet.com",
                                "MessageUUID": "124",
                                "MessageID": 20547681647433001,
                                "MessageHref": "https://api.mailjet.com/v3/message/20547681647433001",
                            },
                        ],
                    },
                ],
            },
        )
        _async_send_message({"to": ["you@test.local"], "cc": [], "bcc": [], "subject": "Hi", "body": "Hello"})
        assert self.EXC_TEXT not in caplog.text

    def test_raises_on_error(self, anymail_mailjet_settings, caplog, requests_mock):
        """An exception is raised, to make Huey retry the task."""
        requests_mock.post(
            f"{anymail_mailjet_settings.ANYMAIL['MAILJET_API_URL']}send",
            # https://dev.mailjet.com/email/guides/send-api-v31/#send-in-bulk
            json={
                "Messages": [
                    {
                        "Errors": [
                            {
                                "ErrorIdentifier": "88b5ca9f-5f1f-42e7-a45e-9ecbad0c285e",
                                "ErrorCode": "send-0003",
                                "StatusCode": 400,
                                "ErrorMessage": 'At least "HTMLPart", "TextPart" or "TemplateID" must be provided.',
                                "ErrorRelatedTo": ["HTMLPart", "TextPart"],
                            },
                        ],
                        "Status": "error",
                    },
                ],
            },
        )
        _async_send_message({"to": ["you@test.local"], "cc": [], "bcc": [], "subject": "Hi", "body": "Hello"})
        assert self.EXC_TEXT in caplog.text

    def test_logs_to_sentry_after_using_all_retries(self, anymail_mailjet_settings, caplog, requests_mock, mocker):
        error_payload = {
            "Errors": [
                {
                    "ErrorIdentifier": "88b5ca9f-5f1f-42e7-a45e-9ecbad0c285e",
                    "ErrorCode": "send-0003",
                    "StatusCode": 400,
                    "ErrorMessage": 'At least "HTMLPart", "TextPart" or "TemplateID" must be provided.',
                    "ErrorRelatedTo": ["HTMLPart", "TextPart"],
                },
            ],
            "Status": "error",
        }
        requests_mock.post(
            f"{anymail_mailjet_settings.ANYMAIL['MAILJET_API_URL']}send",
            # https://dev.mailjet.com/email/guides/send-api-v31/#send-in-bulk
            json={"Messages": [error_payload]},
        )
        sentry_mock = mocker.patch("itou.utils.tasks.sentry_sdk.capture_message")
        _async_send_message(
            {"to": ["you@test.local"], "cc": [], "bcc": [], "subject": "Hi", "body": "Hello"}, retries=0
        )
        sentry_mock.assert_called_once_with(f"Could not send email: {error_payload}", "error")
        assert self.EXC_TEXT not in caplog.text
