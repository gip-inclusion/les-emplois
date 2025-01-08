import urllib

from dateutil.relativedelta import relativedelta
from django.conf import settings

from itou.utils.apis.updown import UpdownApiClient


def test_request(updown_respx_mock):
    start, _ = updown_respx_mock
    end = start + relativedelta(days=1)

    response = UpdownApiClient()._request(
        endpoint=f"/checks/{settings.API_UPDOWN_CHECK_ID}/metrics/", start=start, end=end
    )
    assert settings.API_UPDOWN_TOKEN in str(response.url)
    assert urllib.parse.quote(start.isoformat()) in str(response.url)
    assert urllib.parse.quote(end.isoformat()) in str(response.url)
