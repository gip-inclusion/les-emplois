from django.utils import timezone

from itou.analytics import api_usage, models
from itou.utils.apis.datadog import DatadogApiClient


# Used in `datadog_client` fixture.
# See conftest.py
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


def test_collect_analytics_data_return_all_codes(datadog_client):
    now = timezone.now()
    assert api_usage.collect_analytics_data(client=datadog_client, before=now).keys() == {
        models.DatumCode.API_TOTAL_CALLS,
        models.DatumCode.API_TOTAL_UV,
        models.DatumCode.API_TOTAL_CALLS_CANDIDATS,
        models.DatumCode.API_TOTAL_UV_CANDIDATS,
        models.DatumCode.API_TOTAL_CALLS_GEIQ,
        models.DatumCode.API_TOTAL_UV_GEIQ,
        models.DatumCode.API_TOTAL_CALLS_ER,
        models.DatumCode.API_TOTAL_UV_ER,
        models.DatumCode.API_TOTAL_CALLS_MARCHE,
        models.DatumCode.API_TOTAL_CALLS_SIAES,
        models.DatumCode.API_TOTAL_CALLS_STRUCTURES,
    }


def test_collect_analytics_data_with_data(datadog_client):
    now = timezone.now()
    assert api_usage.collect_analytics_data(client=datadog_client, before=now) == {
        models.DatumCode.API_TOTAL_CALLS: 1,
        models.DatumCode.API_TOTAL_UV: 2,
        models.DatumCode.API_TOTAL_CALLS_CANDIDATS: 3,
        models.DatumCode.API_TOTAL_UV_CANDIDATS: 4,
        models.DatumCode.API_TOTAL_CALLS_GEIQ: 5,
        models.DatumCode.API_TOTAL_UV_GEIQ: 6,
        models.DatumCode.API_TOTAL_CALLS_ER: 7,
        models.DatumCode.API_TOTAL_UV_ER: 8,
        models.DatumCode.API_TOTAL_CALLS_MARCHE: 9,
        models.DatumCode.API_TOTAL_CALLS_SIAES: 10,
        models.DatumCode.API_TOTAL_CALLS_STRUCTURES: 11,
    }
