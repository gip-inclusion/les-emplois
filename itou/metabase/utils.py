import datetime
import urllib

import httpx
from django.conf import settings
from django.utils import timezone


def convert_boolean_to_int(func, *args, **kwargs):
    # True => 1, False => 0, None => None.
    b = func(*args, **kwargs)
    return None if b is None else int(b)


def convert_datetime_to_local_date(func, *args, **kwargs):
    dt = func(*args, **kwargs)
    if isinstance(dt, datetime.datetime):
        # Datetimes are stored in UTC.
        return timezone.localdate(dt)
    return dt


def build_dbt_daily():
    httpx.post(
        urllib.parse.urljoin(settings.AIRFLOW_BASE_URL, "api/v1/dags/dbt_daily/dagRuns"),
        json={"conf": {}},
    ).raise_for_status()
