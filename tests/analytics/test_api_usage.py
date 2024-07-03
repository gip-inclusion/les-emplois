from django.utils import timezone

from itou.analytics import api_usage, models


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
        models.DatumCode.API_TOTAL_UV_SIAES,
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
        models.DatumCode.API_TOTAL_UV_SIAES: 11,
        models.DatumCode.API_TOTAL_CALLS_STRUCTURES: 12,
    }
