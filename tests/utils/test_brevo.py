import httpx
import pytest

from itou.utils.brevo import BREVO_API_URL, BrevoClient, async_delete_contact
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

    respx_mock.post(f"{BREVO_API_URL}/contacts/import", json=payload).mock(
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


@pytest.mark.parametrize("status_code", [204, 404])
def test_delete_contact(respx_mock, django_capture_on_commit_callbacks, status_code, caplog, brevo_client):
    email = "somebody@mail.com"
    respx_mock.delete(f"{BREVO_API_URL}/contacts/{email}?identifierType=email_id").mock(
        return_value=httpx.Response(status_code=status_code)
    )

    with django_capture_on_commit_callbacks(execute=True):
        async_delete_contact(email)

    assert [record.levelname for record in caplog.records] == ["INFO"]


def test_delete_contact_request_error(mocker, caplog, snapshot, brevo_client):
    mocker.patch("itou.utils.brevo.httpx.Client.delete", side_effect=httpx.RequestError("Connection timed out"))

    with pytest.raises(httpx.RequestError):
        # using the client directly to simulate the error, as async_delete_contact does not propagate it,
        # but catch it for managing retries
        brevo_client.delete_contact("somebody@mail.com")

    error_record = next(record for record in caplog.records if record.levelname == "ERROR")
    assert error_record.message == snapshot(name="brevo-api-request-error-connection-timed-out")


def test_delete_contact_on_http_status_error(respx_mock, caplog, snapshot, brevo_client):
    email = "somebody@mail.com"
    respx_mock.delete(f"{BREVO_API_URL}/contacts/{email}?identifierType=email_id").mock(
        return_value=httpx.Response(status_code=500)
    )

    with pytest.raises(httpx.HTTPStatusError):
        # using the client directly to simulate the error, as async_delete_contact does not propagate it
        # but catch it for managing retries
        brevo_client.delete_contact("somebody@mail.com")

    error_record = next(record for record in caplog.records if record.levelname == "ERROR")
    assert error_record.message == snapshot(name="brevo-api-http-error-500")


@pytest.mark.parametrize("retries", [1, 100, 200])
def test_async_delete_contact_retries_warning(
    respx_mock, django_capture_on_commit_callbacks, retries, caplog, snapshot, brevo_client
):
    email = "somebody@email.com"
    respx_mock.delete(f"{BREVO_API_URL}/contacts/{email}?identifierType=email_id").mock(
        return_value=httpx.Response(status_code=503)
    )

    with django_capture_on_commit_callbacks(execute=True):
        async_delete_contact(email, retries=retries)

    assert respx_mock.calls.called

    if retries % 100 == 0:
        warning_record = next(record for record in caplog.records if record.levelname == "WARNING")
        assert warning_record.message == snapshot(name=f"attempting-to-delete-email-{retries}-retries")
