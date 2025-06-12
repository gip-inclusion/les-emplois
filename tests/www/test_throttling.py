import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains

from tests.users.factories import PrescriberFactory


@pytest.fixture
def one_request_per_minute(mocker):
    mocker.patch("itou.utils.throttling.FailSafeUserRateThrottle.rate", "1/minute")


def test_throttling(client, one_request_per_minute):
    client.force_login(PrescriberFactory())
    response = client.get(reverse("dashboard:index"))
    assert response.status_code == 200
    response = client.get(reverse("dashboard:index"))
    assertContains(
        response,
        "<p>Vous avez effectué trop de requêtes. Réessayez dans 60 secondes.</p>",
        status_code=429,
    )


def test_throttling_ignores_public_views(client, one_request_per_minute):
    client.force_login(PrescriberFactory())
    response = client.get(reverse("search:employers_home"))
    assert response.status_code == 200
    response = client.get(reverse("search:employers_home"))
    # Middleware let the request through.
    assert response.status_code == 200


def test_throttling_ignores_anonymous_user(client, one_request_per_minute):
    response = client.get(reverse("search:employers_home"))
    assert response.status_code == 200
    response = client.get(reverse("search:employers_home"))
    # Middleware let the request through.
    assert response.status_code == 200
