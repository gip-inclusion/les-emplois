from dateutil.relativedelta import relativedelta

from itou.utils.apis.sentry import SentryApiClient

from . import models


def collect_analytics_data(before):
    start = (before - relativedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = before.replace(hour=0, minute=0, second=0, microsecond=0)
    sentry_metrics = SentryApiClient().get_metrics(start=start, end=end)

    # Data is stored as an integer.
    return {
        models.DatumCode.TECH_SENTRY_APDEX: round(sentry_metrics["apdex"] * 10000),
        models.DatumCode.TECH_SENTRY_FAILURE_RATE: round(sentry_metrics["failure_rate"] * 10000),
    }
