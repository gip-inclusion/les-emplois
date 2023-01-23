import functools

import httpx
from django.conf import settings


class Monitor:
    headers = {"Authorization": f"DSN {settings.SENTRY_DSN}"}

    def __init__(self, monitor_id):
        self.monitor_id = monitor_id
        self.status = None
        self.checkin_id = None

    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with self:
                return func(*args, **kwargs)

        return wrapper

    def __enter__(self):
        if not settings.SENTRY_DSN:
            return

        response = httpx.post(
            f"https://sentry.io/api/0/monitors/{self.monitor_id}/checkins/",
            headers=self.headers,
            json={"status": "in_progress"},
        )
        response.raise_for_status()
        self.checkin_id = response.json()["id"]

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not settings.SENTRY_DSN:
            return

        response = httpx.put(
            f"https://sentry.io/api/0/monitors/{self.monitor_id}/checkins/{self.checkin_id}/",
            headers=self.headers,
            json={"status": "error" if exc_type else "ok"},
        )
        response.raise_for_status()
