from dateutil.relativedelta import relativedelta

from itou.utils.apis.sentry import SentryApiClient

from . import models


def collect_analytics_data(before):
    start = (before - relativedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = before.replace(hour=0, minute=0, second=0, microsecond=0)

    sentry_metrics = SentryApiClient().get_metrics(start=start, end=end)
    return {
        models.DatumCode.TECH_SENTRY_APDEX: sentry_metrics["apdex"],
        models.DatumCode.TECH_SENTRY_FAILURE_RATE: sentry_metrics["failure_rate"],
    }
