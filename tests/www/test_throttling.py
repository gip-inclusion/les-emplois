import time
from datetime import timedelta

import pytest
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
from pytest_django.asserts import assertContains

from itou.api.throttling import FailSafeUserRateThrottle
from tests.users.factories import PrescriberFactory


@pytest.fixture
def one_request_per_minute(mocker):
    mocker.patch("itou.utils.throttling.FailSafeAnonRateThrottle.rate", "1/minute")
    mocker.patch("itou.utils.throttling.FailSafeUserRateThrottle.rate", "1/minute")


@pytest.mark.parametrize("user_factory", [None, PrescriberFactory])
def test_throttling(client, user_factory, one_request_per_minute):
    if user_factory is not None:
        client.force_login(user_factory())
        url = reverse("dashboard:index")
    else:
        url = reverse("search:home")

    response = client.get(url)
    assert response.status_code == 200
    response = client.get(url)
    assertContains(
        response,
        "<p>Vous avez effectué trop de requêtes. Réessayez dans",
        status_code=429,
    )


def test_is_throttled(rf):
    class OnePerMinuteThrottle(FailSafeUserRateThrottle):
        rate = "1/minute"

    request = rf.get(reverse("search:home"))
    request.user = AnonymousUser()
    OnePerMinuteThrottle().allow_request(request, None)
    assert OnePerMinuteThrottle().is_throttled(request, None) is True
    now = time.time()
    OnePerMinuteThrottle.timer = lambda *args: now + timedelta(minutes=1).total_seconds()
    assert OnePerMinuteThrottle().is_throttled(request, None) is False
