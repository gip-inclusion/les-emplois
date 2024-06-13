import pytest
from django.core.mail.message import EmailMessage
from factory import Faker
from requests.exceptions import ConnectTimeout

from itou.emails.models import Email
from itou.emails.tasks import AsyncEmailBackend, _async_send_message


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
    HUEY_TEXT = "Unhandled exception in task"

    @staticmethod
    def assert_fields_unchanged(email, fresh_email):
        for attr in ("to", "cc", "bcc", "subject", "body_text", "from_email", "reply_to", "created_at"):
            assert getattr(email, attr) == getattr(fresh_email, attr)

    def test_send_ok(self, anymail_mailjet_settings, caplog, requests_mock, success_response):
        email = Email.objects.create(to=["you@test.local"], cc=[], bcc=[], subject="Hi", body_text="Hello")
        requests_mock.post(f"{anymail_mailjet_settings.ANYMAIL['MAILJET_API_URL']}send", json=success_response)
        _async_send_message(email.pk)
        assert self.EXC_TEXT not in caplog.text
        fresh_email = Email.objects.get(pk=email.pk)
        self.assert_fields_unchanged(email, fresh_email)
        assert fresh_email.esp_response == success_response

    def test_raises_on_error(self, anymail_mailjet_settings, caplog, error_response, requests_mock):
        """An exception is raised, to make Huey retry the task."""
        email = Email.objects.create(to=["you@test.local"], cc=[], bcc=[], subject="Hi", body_text="Hello")
        requests_mock.post(f"{anymail_mailjet_settings.ANYMAIL['MAILJET_API_URL']}send", json=error_response)
        _async_send_message(email.pk)
        assert self.EXC_TEXT in caplog.text
        fresh_email = Email.objects.get(pk=email.pk)
        self.assert_fields_unchanged(email, fresh_email)
        assert fresh_email.esp_response == error_response

    def test_logs_to_sentry_after_using_all_retries(
        self, anymail_mailjet_settings, caplog, error_response, mocker, requests_mock
    ):
        # https://dev.mailjet.com/email/guides/send-api-v31/#send-in-bulk
        email = Email.objects.create(to=["you@test.local"], cc=[], bcc=[], subject="Hi", body_text="Hello")
        requests_mock.post(f"{anymail_mailjet_settings.ANYMAIL['MAILJET_API_URL']}send", json=error_response)
        sentry_mock = mocker.patch("itou.emails.tasks.sentry_sdk.capture_message")
        _async_send_message(email.pk, retries=0)
        sentry_mock.assert_called_once_with(f"Could not send email.pk={email.pk}.", "error")
        assert self.EXC_TEXT not in caplog.text
        fresh_email = Email.objects.get(pk=email.pk)
        self.assert_fields_unchanged(email, fresh_email)
        assert fresh_email.esp_response == error_response

    def test_nonexistent_email(self, caplog):
        _async_send_message(0)
        assert self.EXC_TEXT not in caplog.text
        assert "Not sending email_id=0, it does not exist in the database." in caplog.text

    def test_mailjet_timeout(self, anymail_mailjet_settings, caplog, requests_mock):
        # https://dev.mailjet.com/email/guides/send-api-v31/#send-in-bulk
        email = Email.objects.create(to=["you@test.local"], cc=[], bcc=[], subject="Hi", body_text="Hello")
        requests_mock.post(
            f"{anymail_mailjet_settings.ANYMAIL['MAILJET_API_URL']}send",
            exc=ConnectTimeout,
        )
        _async_send_message(email.pk)
        assert self.EXC_TEXT in caplog.text
        assert email.esp_response is None

    def test_mailjet_unavailable_json_response(self, anymail_mailjet_settings, caplog, requests_mock):
        email = Email.objects.create(to=["you@test.local"], cc=[], bcc=[], subject="Hi", body_text="Hello")
        error = {"error": "Server unavailable"}
        requests_mock.post(f"{anymail_mailjet_settings.ANYMAIL['MAILJET_API_URL']}send", json=error)
        _async_send_message(email.pk)
        assert self.EXC_TEXT in caplog.text
        email.refresh_from_db()
        assert email.esp_response == error

    def test_mailjet_unavailable_html_response(self, anymail_mailjet_settings, caplog, requests_mock):
        email = Email.objects.create(to=["you@test.local"], cc=[], bcc=[], subject="Hi", body_text="Hello")
        error_text = "<html><h1>503 Maintenance</h1></html>"
        requests_mock.post(
            f"{anymail_mailjet_settings.ANYMAIL['MAILJET_API_URL']}send",
            text=error_text,
        )
        _async_send_message(email.pk)
        assert self.EXC_TEXT in caplog.text
        assert f"Received invalid response from Mailjet, email_id={email.pk}. Payload: {error_text}" in caplog.text
        assert email.esp_response is None

    def test_task_failure(self, anymail_mailjet_settings, caplog, requests_mock):
        email = Email.objects.create(to=["you@test.local"], cc=[], bcc=[], subject="Hi", body_text="Hello")
        requests_mock.post(
            f"{anymail_mailjet_settings.ANYMAIL['MAILJET_API_URL']}send",
            exc=Exception("Test"),
        )
        _async_send_message(email.pk)
        # Simply to pair with "assert self.HUEY_TEXT not in caplog.text" in test_django_settings.
        assert self.HUEY_TEXT in caplog.text

    def test_django_settings(self, caplog, settings):
        email = Email.objects.create(to=["you@test.local"], cc=[], bcc=[], subject="Hi", body_text="Hello")
        _async_send_message(email.pk)
        # No retries of the task.
        assert self.EXC_TEXT not in caplog.text
        assert self.HUEY_TEXT not in caplog.text
        assert email.esp_response is None
