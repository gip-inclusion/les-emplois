import sentry_sdk
from django.conf import settings


def silently_report_exception(e):
    if settings.DEBUG:
        # The django 500 page is used, it does not include this template tag.
        raise
    # Keep going, we may be rendering the 500 page.
    sentry_sdk.capture_exception(e)
