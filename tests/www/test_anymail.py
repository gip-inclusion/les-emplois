import base64


def test_access(client, settings):
    # Setup access
    settings.ANYMAIL = dict(settings.ANYMAIL) | {"WEBHOOK_SECRET": "S3cr3t"}

    # Try without credentials
    response = client.post("/webhooks/anymail/mailjet/tracking/", content_type="application/json", data=[])
    assert response.status_code == 400

    # and with
    response = client.post(
        "/webhooks/anymail/mailjet/tracking/",
        content_type="application/json",
        data=[],
        headers={"Authorization": "Basic " + base64.b64encode(b"S3cr3t").decode()},
    )
    assert response.status_code == 200
