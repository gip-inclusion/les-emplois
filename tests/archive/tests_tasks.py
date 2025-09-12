import httpx
import pytest
from django.conf import settings

from itou.archive.tasks import async_delete_contact
from tests.utils.test_brevo import brevo_client_fixture  # noqa: F401


@pytest.mark.parametrize("status_code", [204, 404])
def test_delete_contact(respx_mock, django_capture_on_commit_callbacks, status_code, caplog, brevo_client):
    email = "somebody@mail.com"
    respx_mock.delete(f"{settings.BREVO_API_URL}/contacts/{email}?identifierType=email_id").mock(
        return_value=httpx.Response(status_code=status_code)
    )

    with django_capture_on_commit_callbacks(execute=True):
        async_delete_contact(email)

    assert [record.levelname for record in caplog.records] == ["INFO"]


@pytest.mark.parametrize("retries", [1, 100, 200])
def test_async_delete_contact_retries_warning(
    respx_mock, django_capture_on_commit_callbacks, retries, caplog, snapshot, brevo_client
):
    email = "somebody@email.com"
    respx_mock.delete(f"{settings.BREVO_API_URL}/contacts/{email}?identifierType=email_id").mock(
        return_value=httpx.Response(status_code=503)
    )

    with django_capture_on_commit_callbacks(execute=True):
        async_delete_contact(email, retries=retries)

    assert respx_mock.calls.called

    if retries % 100 == 0:
        warning_record = next(record for record in caplog.records if record.levelname == "WARNING")
        assert warning_record.message == snapshot(name=f"attempting-to-delete-email-{retries}-retries")


def test_async_delete_contact_does_not_send_HTTP_request(respx_mock, django_capture_on_commit_callbacks, brevo_client):
    for email, called in [(None, False), ("somebody@email.com_old", False), ("somebody@email.com", True)]:
        respx_mock.delete(f"{settings.BREVO_API_URL}/contacts/{email}?identifierType=email_id").mock(
            return_value=httpx.Response(status_code=204)
        )
        with django_capture_on_commit_callbacks(execute=True):
            async_delete_contact(email)
        assert respx_mock.calls.called is called
