import urllib

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time

from itou.utils.apis.updown import UpdownApiClient


@freeze_time("2024-12-03")
def test_request(updown_respx_mock):
    end = timezone.now()
    start = end - relativedelta(days=1)

    response = UpdownApiClient()._request(
        endpoint=f"/checks/{settings.API_UPDOWN_CHECK_ID}/metrics/", start=start, end=end
    )
    assert settings.API_UPDOWN_TOKEN in str(response.url)
    assert urllib.parse.quote(start.isoformat()) in str(response.url)
    assert urllib.parse.quote(end.isoformat()) in str(response.url)
