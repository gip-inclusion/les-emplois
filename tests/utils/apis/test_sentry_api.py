import urllib

from dateutil.relativedelta import relativedelta
from django.conf import settings

from itou.utils.apis.sentry import SentryApiClient


def test_request(sentry_respx_mock):
    start, _ = sentry_respx_mock
    end = start + relativedelta(days=1)

    response = SentryApiClient()._request(start, end)
    assert response.status_code == 200
    assert settings.API_SENTRY_STATS_TOKEN in response.request.headers["authorization"]
    assert urllib.parse.quote(start.isoformat()) in str(response.url)
    assert urllib.parse.quote(end.isoformat()) in str(response.url)
