from itou.utils.apis.datadog import DatadogApiClient

from . import models


def collect_analytics_data(before, client=None):
    if not client:
        client = DatadogApiClient()
    # Calling the API this way causes many Too Many Requests error and increases total time treatment
    # (less than a minute) but it makes code shorter and easily understandable.
    # As treatment time is not critical, let's just let Tenacty handle retries until a sucessful reponse arrives.
    return {
        models.DatumCode.API_TOTAL_CALLS: client.count_daily_logs(before),
        models.DatumCode.API_TOTAL_UV: client.count_daily_unique_users(before),
        models.DatumCode.API_TOTAL_CALLS_CANDIDATS: client.count_daily_logs(before, endpoint="candidats/"),
        models.DatumCode.API_TOTAL_UV_CANDIDATS: client.count_daily_unique_users(before, endpoint="candidats/"),
        models.DatumCode.API_TOTAL_CALLS_GEIQ: client.count_daily_logs(before, endpoint="embauches-geiq/"),
        models.DatumCode.API_TOTAL_UV_GEIQ: client.count_daily_unique_users(before, endpoint="embauches-geiq/"),
        models.DatumCode.API_TOTAL_CALLS_ER: client.count_daily_logs(before, endpoint="employee-records/"),
        models.DatumCode.API_TOTAL_UV_ER: client.count_daily_unique_users(before, endpoint="employee-records/"),
        models.DatumCode.API_TOTAL_CALLS_MARCHE: client.count_daily_logs(before, endpoint="marche/"),
        models.DatumCode.API_TOTAL_CALLS_SIAES: client.count_daily_logs(before, endpoint="siaes/"),
        models.DatumCode.API_TOTAL_UV_SIAES: client.count_daily_unique_ip_addresses(before, endpoint="siaes/"),
        models.DatumCode.API_TOTAL_CALLS_STRUCTURES: client.count_daily_logs(before, endpoint="structures/"),
    }
