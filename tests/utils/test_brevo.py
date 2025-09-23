import httpx
import pytest
from django.conf import settings

from itou.utils.brevo import BrevoClient
from tests.users.factories import JobSeekerFactory


@pytest.fixture(name="brevo_client")
def brevo_client_fixture(settings):
    settings.BREVO_API_KEY = "BREVO_API_KEY"
    return BrevoClient()


@pytest.fixture(name="mock_httpx_client")
def mock_httpx_client_fixture(mocker):
    mock_client = mocker.Mock()
    mocker.patch("itou.utils.brevo.httpx.Client", return_value=mock_client)
    return mock_client


def test_brevo_client_context_manager(mock_httpx_client, caplog, brevo_client):
    with brevo_client:
        assert brevo_client.client == mock_httpx_client

    mock_httpx_client.close.assert_called_once()


def test_brevo_client_context_manager_with_exception(mock_httpx_client, caplog, brevo_client):
    with pytest.raises(Exception, match="Test exception"):
        with brevo_client:
            raise Exception("Test exception")

    mock_httpx_client.close.assert_called_once()

    error_record = next(record for record in caplog.records if record.levelname == "ERROR")
    assert "An exception occurred in BrevoClient: Test exception" in error_record.message


@pytest.mark.parametrize("status_code,content", [(202, "OK"), (400, "Bad Request"), (500, "Internal Server Error")])
def test_import_users(respx_mock, caplog, status_code, content, brevo_client):
    user = JobSeekerFactory()
    payload = {
        "listIds": [31],
        "emailBlacklist": False,
        "smsBlacklist": False,
        "updateExistingContacts": False,
        "emptyContactsAttributes": False,
        "jsonBody": [{"email": user.email}],
    }

    respx_mock.post(f"{settings.BREVO_API_URL}/contacts/import", json=payload).mock(
        return_value=httpx.Response(status_code, content=content)
    )

    brevo_client.import_users([user], 31, lambda x: {"email": x.email})

    assert respx_mock.calls.called

    if status_code != 202:
        error_record = next(record for record in caplog.records if record.levelname == "ERROR")
        assert (
            f"Brevo API: Some emails were not imported, status_code={status_code}, content={content}"
            in error_record.message
        )


def test_import_contacts_request_error(mocker, caplog, brevo_client):
    mocker.patch("itou.utils.brevo.httpx.Client.post", side_effect=httpx.RequestError("Connection timed out"))

    with pytest.raises(httpx.RequestError):
        brevo_client._import_contacts([{"email": "user1@example.com"}], 1, lambda x: x)

    error_record = next(record for record in caplog.records if record.levelname == "ERROR")
    assert error_record.message == "Brevo API: Request failed: Connection timed out"


def test_delete_contact_request_error(mocker, caplog, snapshot, brevo_client):
    email = "somebody@mail.com"
    mocker.patch("itou.utils.brevo.httpx.Client.delete", side_effect=httpx.RequestError("Connection timed out"))

    with pytest.raises(httpx.RequestError):
        # using the client directly to simulate the error, as async_delete_contact does not propagate it,
        # but catch it for managing retries
        brevo_client.delete_contact(email)

    error_record = next(record for record in caplog.records if record.levelname == "ERROR")
    assert error_record.message == snapshot(name="brevo-api-request-error-connection-timed-out")
    assert email not in caplog.text


def test_delete_contact_on_http_status_error(respx_mock, caplog, snapshot, brevo_client):
    email = "somebody@mail.com"
    respx_mock.delete(f"{settings.BREVO_API_URL}/contacts/{email}?identifierType=email_id").mock(
        return_value=httpx.Response(status_code=500)
    )

    with pytest.raises(httpx.HTTPStatusError):
        # using the client directly to simulate the error, as async_delete_contact does not propagate it
        # but catch it for managing retries
        brevo_client.delete_contact(email)

    error_record = next(record for record in caplog.records if record.levelname == "ERROR")
    assert error_record.message == snapshot(name="brevo-api-http-error-500")
    assert email not in caplog.text


def test_delete_contact_on_400(respx_mock, caplog, brevo_client):
    email = "accent@démonstration.fr"
    respx_mock.delete(f"{settings.BREVO_API_URL}/contacts/{email}?identifierType=email_id").mock(
        return_value=httpx.Response(
            status_code=400, json={"code": "invalid_parameter", "message": "Invalid email address"}
        )
    )

    # should not raise
    brevo_client.delete_contact(email)
    assert respx_mock.calls.called
    assert "Brevo API: email considered as invalid - no need to delete it" in caplog.text

    email = "test@example.com"
    respx_mock.delete(f"{settings.BREVO_API_URL}/contacts/{email}?identifierType=email_id").mock(
        return_value=httpx.Response(status_code=400, json={"code": "other_error", "message": "Some other error"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        brevo_client.delete_contact(email)
    assert respx_mock.calls.called
