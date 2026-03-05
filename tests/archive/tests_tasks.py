import httpx
import pytest
from django.conf import settings

from itou.archive.tasks import async_delete_contact
from tests.utils.test_brevo import brevo_client_fixture  # noqa: F401
from tests.utils.testing import execute_tasks


@pytest.mark.parametrize("status_code", [204, 404])
def test_delete_contact(respx_mock, status_code, caplog, brevo_client):
    email = "somebody@mail.com"
    respx_mock.delete(f"{settings.BREVO_API_URL}/contacts/{email}?identifierType=email_id").mock(
        return_value=httpx.Response(status_code=status_code)
    )

    async_delete_contact(email)
    execute_tasks()

    assert [record.levelname for record in caplog.records] == ["INFO"]


@pytest.mark.parametrize("retries", [1, 100, 200])
def test_async_delete_contact_retries_warning(respx_mock, retries, caplog, snapshot, brevo_client):
    email = "somebody@email.com"
    respx_mock.delete(f"{settings.BREVO_API_URL}/contacts/{email}?identifierType=email_id").mock(
        return_value=httpx.Response(status_code=503)
    )

    async_delete_contact(email, retries=retries)
    execute_tasks()

    assert respx_mock.calls.called

    if retries % 100 == 0:
        warning_record = next(record for record in caplog.records if record.levelname == "WARNING")
        assert warning_record.message == snapshot(name=f"attempting-to-delete-email-{retries}-retries")


def test_async_delete_contact_does_not_send_HTTP_request(respx_mock, brevo_client):
    for email, called in [
        (None, False),
        ("somebody@email.com_old", False),
        ("somebody@email.old", False),
        ("somebody@email.back", False),
        ("somebody@email.zip", False),
        ("somebody@email.tar", False),
        ("somebody@email.com", True),  # positive case to avoid any test misconfiguration
    ]:
        respx_mock.delete(f"{settings.BREVO_API_URL}/contacts/{email}?identifierType=email_id").mock(
            return_value=httpx.Response(status_code=204)
        )
        async_delete_contact(email)
        execute_tasks()
        assert respx_mock.calls.called is called
