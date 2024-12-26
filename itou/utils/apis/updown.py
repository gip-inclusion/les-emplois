import logging

import httpx
import tenacity
from django.conf import settings


logger = logging.getLogger(__name__)


class UpdownApiClient:
    def __init__(self):
        self.client = httpx.Client(
            base_url=f"{settings.API_UPDOWN_BASE_URL}",
            params={"api-key": settings.API_UPDOWN_TOKEN},
            headers={
                "Content-Type": "application/json",
            },
        )

    @tenacity.retry(wait=tenacity.wait_fixed(2), stop=tenacity.stop_after_attempt(8))
    def _request(self, endpoint, start, end):
        params = {
            "from": start.isoformat(),
            "to": end.isoformat(),
        }
        return self.client.get(endpoint, params=params).raise_for_status()

    def get_metrics(self, start, end):
        endpoint = f"/checks/{settings.API_UPDOWN_CHECK_ID}/metrics/"
        response = self._request(endpoint=endpoint, start=start, end=end)
        data = response.json()
        # Apdex is optional because it's unavailable for data before November 1st, 2024.
        return {
            "uptime": data["uptime"],
            "apdex": data.get("apdex"),
        }
