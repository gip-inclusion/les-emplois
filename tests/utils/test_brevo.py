import httpx
import pytest

from itou.utils.brevo import BREVO_API_URL, BrevoClient
from tests.users.factories import JobSeekerFactory


@pytest.fixture(name="brevo_client")
def brevo_client_fixture(settings):
    settings.BREVO_API_KEY = "BREVO_API_KEY"
    return BrevoClient()


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
