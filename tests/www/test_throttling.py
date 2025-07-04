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
