from dateutil.relativedelta import relativedelta

from itou.analytics import models
from itou.utils.apis.sentry import SentryApiClient
from itou.utils.apis.updown import UpdownApiClient


def collect_analytics_data(before):
    start = (before - relativedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = before.replace(hour=0, minute=0, second=0, microsecond=0)
    sentry_metrics = SentryApiClient().get_metrics(start=start, end=end)
    # uptime is already multiplied by 100 by Updown.
    updown_metrics = UpdownApiClient().get_metrics(start=start, end=end)
    data = {
        models.DatumCode.TECH_SENTRY_APDEX: round(sentry_metrics["apdex"] * 10000),
        models.DatumCode.TECH_SENTRY_FAILURE_RATE: round(sentry_metrics["failure_rate"] * 10000),
        models.DatumCode.TECH_UPDOWN_UPTIME: round(updown_metrics["uptime"]),
    }
    if updown_metrics.get("apdex"):
        data[models.DatumCode.TECH_UPDOWN_APDEX] = round(updown_metrics["apdex"] * 10000)

    return data
