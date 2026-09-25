import pytest


@pytest.fixture
def mailjet_success_response():
    # https://dev.mailjet.com/email/guides/send-api-v31/#send-in-bulk
    return {
        "Messages": [
            {
                "Status": "success",
                "To": [
                    {
                        "Email": "you@test.local",
                        "MessageUUID": "124",
                        "MessageID": 20547681647433001,
                        "MessageHref": "https://api.mailjet.com/v3/message/20547681647433001",
                    },
                ],
            },
        ],
    }


@pytest.fixture
def success_response():
    # https://developers.brevo.com/reference/send-transac-email
    return {"messageId": "<202608041342.16839723220@smtp-relay.mailin.fr>"}


@pytest.fixture
def mailjet_error_response():
    # https://dev.mailjet.com/email/guides/send-api-v31/#send-in-bulk
    return {
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
    }


@pytest.fixture
def error_response():
    # https://developers.brevo.com/reference/send-transac-email
    return {
        "code": "invalid_parameter",
        "message": 'At least "htmlContent", "textContent" or "templateId" must be provided.',
    }


@pytest.fixture
def mailjet_messagehistory_response():
    # https://dev.mailjet.com/email/reference/messages#v3_get_messagehistory_message_ID
    return {
        "Count": 1,
        "Data": [
            {
                "Comment": "",
                "EventAt": 1514764800,
                "EventType": "opened",
                "State": "",
                "Useragent": (
                    "Mozilla/5.0 (Windows NT 5.1; rv:11.0) Gecko Firefox/11.0 (via ggpht.com GoogleImageProxy)"
                ),
                "UseragentID": 1234,
            }
        ],
        "Total": 1,
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
