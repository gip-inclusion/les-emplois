import json
import logging

import httpx
import tenacity
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.utils import timezone


logger = logging.getLogger(__name__)


class DatadogBadResponseException(Exception):
    def __init__(self, data_sent, data_received):
        self.data_sent = data_sent
        self.data_received = data_received

    def __str__(self):
        return f"DatadogBadResponseException(data_sent={self.data_sent}, data_received='{self.data_received}.')"


class DatadogApiClient:
    def __init__(self):
        self.client = httpx.Client(
            base_url=settings.API_DATADOG_BASE_URL,
            headers={
                "DD-API-KEY": settings.API_DATADOG_API_KEY,
                "DD-APPLICATION-KEY": settings.API_DATADOG_APPLICATION_KEY,
                "Content-Type": "application/json",
            },
        )

    @tenacity.retry(wait=tenacity.wait_fixed(2), stop=tenacity.stop_after_attempt(8))
    def _request(self, data):
        response = self.client.post("/logs/analytics/aggregate", content=json.dumps(data))
        response.raise_for_status()
        return response

    def _get_data_from_datadog(self, data=None):
        response = self._request(data)
        data_received = response.json()["data"]["buckets"]
        if not data_received:
            # An empty bucket means "no result".
            return 0
        try:
            data_received = data_received[0]["computes"]["c0"]
        except (IndexError, KeyError):
            exc = DatadogBadResponseException(data_sent=data, data_received=response.json())
            logger.error(exc)
            raise exc

        return data_received

    def default_data(self, metric_kind, agregation_kind, endpoint, start, end):
        # timestamp in milliseconds
        start_ts = round(start.timestamp()) * 1000
        end_ts = round(end.timestamp()) * 1000
        data = {
            "compute": [{"metric": metric_kind, "aggregation": agregation_kind, "type": "total"}],
            "filter": {
                "query": f"@http.url:/api/v1/{endpoint}* @logger.method_name:log_response -@http.url:/api/v1/redoc/* ",
                "from": f"{start_ts}",
                "to": f"{end_ts}",
                "indexes": ["*"],
            },
            "group_by": [],
        }
        return data

    def count_daily_logs(self, before="", endpoint=""):
        if not before:
            before = timezone.now()
        start = (before - relativedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = before.replace(hour=0, minute=0, second=0, microsecond=0)
        data = self.default_data(metric_kind="count", agregation_kind="count", endpoint=endpoint, start=start, end=end)
        return self._get_data_from_datadog(data=data)

    def count_daily_unique_users(self, before="", endpoint=""):
        if not before:
            before = timezone.now()
        start = (before - relativedelta(days=1)).replace(hour=0, minute=0, second=0)
        end = before.replace(hour=0, minute=0, second=0)
        data = self.default_data(
            metric_kind="@usr.id", agregation_kind="cardinality", endpoint=endpoint, start=start, end=end
        )
        return self._get_data_from_datadog(data=data)
