import pytest


@pytest.fixture
def success_response():
    # https://developers.brevo.com/reference/send-transac-email
    return {"messageId": "<202608041342.16839723220@smtp-relay.mailin.fr>"}


@pytest.fixture
def error_response():
    # https://developers.brevo.com/reference/send-transac-email
    return {
        "code": "invalid_parameter",
        "message": 'At least "htmlContent", "textContent" or "templateId" must be provided.',
    }


@pytest.fixture
def brevo_events_response():
    # https://developers.brevo.com/reference/get-email-event-report
    return {
        "events": [
            {
                "email": "you@test.local",
                "date": "2026-08-04T13:42:00.000Z",
                "messageId": "<202608041342.16839723220@smtp-relay.mailin.fr>",
                "event": "delivered",
                "from": "unit-test@tests.com",
            }
        ]
    }
