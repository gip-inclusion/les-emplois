from functools import partial

import pytest
from django.test import override_settings
from django.utils import timezone

from itou.analytics import api_usage
from itou.utils.apis.datadog import DatadogApiClient


def _mocked_client(mocker, now):
    mapping = {
        "count_daily_logs": {
            "": 1,
            "candidats/": 3,
            "embauches-geiq/": 5,
            "employee-records/": 7,
            "marche/": 9,
            "siaes/": 10,
            "structures/": 11,
        },
        "count_daily_unique_visitors": {"": 2, "candidats/": 4, "embauches-geiq/": 6, "employee-records/": 8},
    }

    def side_effect_count_daily_logs(*args, **kwargs):
        return mapping["count_daily_logs"][kwargs.get("endpoint", "")]

    def side_effect_count_daily_uv(*args, **kwargs):
        return mapping["count_daily_unique_visitors"][kwargs.get("endpoint", "")]

    client = DatadogApiClient()
    mocker.patch.object(
        client,
        "count_daily_logs",
        call_args=[now],
        side_effect=side_effect_count_daily_logs,
    )
    mocker.patch.object(
        client,
        "count_daily_unique_users",
        call_args=[now],
        side_effect=side_effect_count_daily_uv,
    )
    mocker.patch.object(
        client,
        "count_daily_logs",
        call_args=[now],
        call_kwargs={"endpoint": "candidats/"},
        side_effect=side_effect_count_daily_logs,
    )
    mocker.patch.object(
        client,
        "count_daily_unique_users",
        call_args=[now],
        call_kwargs={"endpoint": "candidats/"},
        side_effect=side_effect_count_daily_uv,
    )
    mocker.patch.object(
        client,
        "count_daily_logs",
        call_args=[now],
        call_kwargs={"endpoint": "embauches-geiq/"},
        side_effect=side_effect_count_daily_logs,
    )
    mocker.patch.object(
        client,
        "count_daily_unique_users",
        call_args=[now],
        call_kwargs={"endpoint": "embauches-geiq/"},
        side_effect=side_effect_count_daily_uv,
    )
    mocker.patch.object(
        client,
        "count_daily_logs",
        call_args=[now],
        call_kwargs={"endpoint": "employee-records/"},
        side_effect=side_effect_count_daily_logs,
    )
    mocker.patch.object(
        client,
        "count_daily_unique_users",
        call_args=[now],
        call_kwargs={"endpoint": "employee-records/"},
        side_effect=side_effect_count_daily_uv,
    )
    mocker.patch.object(
        client,
        "count_daily_logs",
        call_args=[now],
        call_kwargs={"endpoint": "marche/"},
        side_effect=side_effect_count_daily_logs,
    )
    mocker.patch.object(
        client,
        "count_daily_logs",
        call_args=[now],
        call_kwargs={"endpoint": "siaes/"},
        side_effect=side_effect_count_daily_logs,
    )
    mocker.patch.object(
        client,
        "count_daily_logs",
        call_args=[now],
        call_kwargs={"endpoint": "structures/"},
        side_effect=side_effect_count_daily_logs,
    )
    return client


@pytest.fixture
def datadog_client(mocker):
    with override_settings(API_DATADOG_BASE_URL="https://un-toutou-nomme-donnee.fr/"):
        now = timezone.now()
        client = _mocked_client(mocker, now)

        mocker.patch(
            "itou.analytics.api_usage.collect_analytics_data",
            side_effect=partial(api_usage.collect_analytics_data, client=client),
        )
    return client
