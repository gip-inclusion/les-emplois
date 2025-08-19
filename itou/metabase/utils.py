import datetime
import urllib

import httpx
from django.conf import settings
from django.utils import timezone


def convert_boolean_to_int(b):
    # True => 1, False => 0, None => None.
    return None if b is None else int(b)


def convert_datetime_to_local_date(dt):
    if isinstance(dt, datetime.datetime):
        # Datetimes are stored in UTC.
        return timezone.localdate(dt)
    return dt


def compose(f, g):
    # Compose two lambda methods.
    # https://stackoverflow.com/questions/16739290/composing-functions-in-python
    # I had to use this to solve a cryptic
    # `RecursionError: maximum recursion depth exceeded` error
    # when composing convert_boolean_to_int and c["fn"].
    return lambda *a, **kw: f(g(*a, **kw))


def build_dbt_daily():
    httpx.post(
        urllib.parse.urljoin(settings.AIRFLOW_BASE_URL, "api/v1/dags/dbt_daily/dagRuns"),
        json={"conf": {}},
    ).raise_for_status()
