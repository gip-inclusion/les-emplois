import pytest


@pytest.fixture
def success_response():
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
def error_response():
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
                    "Mozilla/5.0 (Windows NT 5.1; rv:11.0) Gecko Firefox/11.0 " "(via ggpht.com GoogleImageProxy)"
                ),
                "UseragentID": 1234,
            }
        ],
        "Total": 1,
    }
