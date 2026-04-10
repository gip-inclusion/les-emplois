from functools import partial

import pytest
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains

from tests.users.factories import PrescriberFactory


@pytest.fixture
def one_request_per_minute(mocker):
    mocker.patch("itou.utils.throttling.FailSafeAnonRateThrottle.rate", "1/minute")
    mocker.patch("itou.utils.throttling.FailSafeUserRateThrottle.rate", "1/minute")


@freeze_time()
@pytest.mark.parametrize("user_factory", [None, partial(PrescriberFactory, membership=True)])
def test_throttling(client, user_factory, one_request_per_minute):
    if user_factory is not None:
        client.force_login(user_factory())
        url = reverse("dashboard:index")
    else:
        url = reverse("search:employers_home")

    response = client.get(url)
    assert response.status_code == 200
    response = client.get(url)
    assertContains(
        response,
        "<p>Vous avez effectué trop de requêtes. Réessayez dans 60 secondes.</p>",
        status_code=429,
    )
