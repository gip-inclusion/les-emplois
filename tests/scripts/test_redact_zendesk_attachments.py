from django.core.management import call_command


def test_redact_zendesk_attachments(respx_mock, monkeypatch):
    URL = "https://plateforme-inclusion.zendesk.com/api/v2/"
    monkeypatch.setattr(
        "itou.scripts.management.commands.redact_zendesk_attachments.ZENDESK_LOGIN",
        "zendesk",
    )
    monkeypatch.setattr(
        "itou.scripts.management.commands.redact_zendesk_attachments.ZENDESK_SECRET",
        "secret",
    )

    get_tickets_url = respx_mock.get(f"{URL}search").respond(
        200,
        json={
            "results": [{"id": 56}],
        },
    )

    get_comments_url = respx_mock.get(f"{URL}tickets/56/comments").respond(
        200,
        json={
            "comments": [
                {
                    "id": 73,
                    "attachments": [
                        {"id": 9, "file_name": "redacted.txt"},
                        {"id": 21, "file_name": "foo.txt"},
                    ],
                }
            ]
        },
    )

    redacted_attachment_url = respx_mock.put(f"{URL}tickets/56/comments/73/attachments/9/redact")
    non_redacted_attachment_url = respx_mock.put(f"{URL}tickets/56/comments/73/attachments/21/redact")

    call_command("redact_zendesk_attachments")

    assert get_tickets_url.call_count == 1
    assert get_comments_url.call_count == 1
    assert redacted_attachment_url.call_count == 0
    assert non_redacted_attachment_url.call_count == 1
