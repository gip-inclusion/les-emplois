import httpx
import pytest

from itou.utils.brevo import BrevoClient
from itou.utils.constants import BREVO_API_URL
from tests.users.factories import JobSeekerFactory


@pytest.fixture(autouse=True)
def setup(settings):
    settings.BREVO_API_KEY = "BREVO_API_KEY"


@pytest.fixture(name="mock_httpx_client")
def mock_httpx_client_fixture(mocker):
    mock_client = mocker.Mock()
    mocker.patch("itou.utils.brevo.httpx.Client", return_value=mock_client)
    return mock_client


def test_brevo_client_context_manager(mock_httpx_client, caplog):
    with BrevoClient() as brevo_client:
        assert brevo_client.client == mock_httpx_client

    mock_httpx_client.close.assert_called_once()


def test_brevo_client_context_manager_with_exception(mock_httpx_client, caplog):
    with pytest.raises(Exception, match="Test exception"):
        with BrevoClient():
            raise Exception("Test exception")

    mock_httpx_client.close.assert_called_once()

    error_record = next(record for record in caplog.records if record.levelname == "ERROR")
    assert "An exception occurred in BrevoClient: Test exception" in error_record.message


@pytest.mark.parametrize("status_code,content", [(202, "OK"), (400, "Bad Request"), (500, "Internal Server Error")])
def test_import_users(respx_mock, caplog, status_code, content):
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

    BrevoClient().import_users([user], 31, lambda x: {"email": x.email})

    assert respx_mock.calls.called

    if status_code != 202:
        error_record = next(record for record in caplog.records if record.levelname == "ERROR")
        assert (
            f"Brevo API: Some emails were not imported, status_code={status_code}, content={content}"
            in error_record.message
        )


def test_import_contacts_request_error(mocker, caplog):
    mocker.patch("itou.utils.brevo.httpx.Client.post", side_effect=httpx.RequestError("Connection timed out"))

    brevo_client = BrevoClient()

    with pytest.raises(httpx.RequestError):
        brevo_client._import_contacts([{"email": "user1@example.com"}], 1, lambda x: x)

    error_record = next(record for record in caplog.records if record.levelname == "ERROR")
    assert error_record.message == "Brevo API: Request failed: Connection timed out"
