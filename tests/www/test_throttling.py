import base64

import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains

from tests.users.factories import PrescriberFactory


@pytest.fixture
def one_request_per_minute(mocker):
    mocker.patch("itou.utils.throttling.FailSafeAnonRateThrottle.rate", "1/minute")
    mocker.patch("itou.utils.throttling.FailSafeUserRateThrottle.rate", "1/minute")


@pytest.mark.parametrize("user_factory", [None, PrescriberFactory])
def test_throttling(client, user_factory, one_request_per_minute):
    if user_factory is not None:
        client.force_login(user_factory())
    response = client.get(reverse("search:employers_home"))
    assert response.status_code == 200
    response = client.get(reverse("search:employers_home"))
    assertContains(
        response,
        "<p>Vous avez effectué trop de requêtes. Réessayez dans 60 secondes.</p>",
        status_code=429,
    )


@pytest.mark.usefixtures("one_request_per_minute")
def test_mailjet_webhook_not_rate_limited(client, settings):
    auth = "user:password"
    settings.ANYMAIL["WEBHOOK_SECRET"] = auth
    encoded_auth = base64.b64encode(auth.encode())
    for _ in range(2):
        response = client.post(
            reverse("mailjet-webhook"),
            # https://dev.mailjet.com/email/guides/webhooks/#blocked-event
            [
                {
                    "event": "blocked",
                    "time": 1430812195,
                    "MessageID": 13792286917004336,
                    "Message_GUID": "1ab23cd4-e567-8901-2345-6789f0gh1i2j",
                    "email": "bounce@mailjet.com",
                    "mj_campaign_id": 0,
                    "mj_contact_id": 0,
                    "customcampaign": "",
                    "CustomID": "helloworld",
                    "Payload": "",
                    "error_related_to": "recipient",
                    "error": "user unknown",
                },
            ],
            content_type="application/json",
            headers={"Authorization": "Basic " + encoded_auth.decode()},
        )
        assert response.status_code == 200
