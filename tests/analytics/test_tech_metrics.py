from django.utils import timezone
from freezegun import freeze_time

from itou.analytics import models, tech


@freeze_time("2024-12-03")
def test_collect_tech_metrics_return_all_codes(sentry_respx_mock, updown_respx_mock):
    now = timezone.now()
    assert tech.collect_analytics_data(before=now).keys() == {
        models.DatumCode.TECH_SENTRY_APDEX,
        models.DatumCode.TECH_SENTRY_FAILURE_RATE,
        models.DatumCode.TECH_UPDOWN_UPTIME,
        models.DatumCode.TECH_UPDOWN_APDEX,
    }


@freeze_time("2024-12-03")
def test_collect_tech_metrics_with_data(sentry_respx_mock, updown_respx_mock):
    now = timezone.now()
    assert tech.collect_analytics_data(before=now) == {
        models.DatumCode.TECH_SENTRY_APDEX: 9556,
        models.DatumCode.TECH_SENTRY_FAILURE_RATE: 812,
        models.DatumCode.TECH_UPDOWN_UPTIME: 100,
        models.DatumCode.TECH_UPDOWN_APDEX: 9860,
    }
