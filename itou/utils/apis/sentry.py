import logging

import httpx
import tenacity
from django.conf import settings


logger = logging.getLogger(__name__)


class SentryApiClient:
    def __init__(self):
        self.client = httpx.Client(
            base_url=f"{settings.API_SENTRY_BASE_URL}/organizations/{settings.API_SENTRY_ORG_NAME}",
            headers={
                "Authorization": f"Bearer {settings.API_SENTRY_STATS_TOKEN}",
                "Content-Type": "application/json",
            },
        )

    @tenacity.retry(wait=tenacity.wait_fixed(2), stop=tenacity.stop_after_attempt(8))
    def _request(self, start, end):
        params = {
            "query": '(event.type:"transaction")',
            "project": settings.API_SENTRY_PROJECT_ID,
            "field": ["apdex()", "failure_rate()"],
            "start": start.isoformat(),
            "end": end.isoformat(),
        }

        response = self.client.get("/events/", params=params)
        response.raise_for_status()
        return response

    def get_metrics(self, start, end):
        response = self._request(start=start, end=end)

        data_received = response.json()["data"][0]
        return {
            "failure_rate": data_received["failure_rate()"],
            "apdex": data_received["apdex()"],
        }
