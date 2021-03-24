"""
Requests library custom configuration
See https://blog.mathieu-leplatre.info/handling-requests-timeout-in-python.html
"""
import requests
from django.conf import settings
from requests.adapters import TimeoutSauce


REQUESTS_TIMEOUT_SECONDS = float(settings.REQUESTS_TIMEOUT_SECONDS)


class ItouTimeout(TimeoutSauce):
    """
    Add a default time out to any requests call instead of specifying ``timeout=..`` kwarg each time.

    Usage
    -----
    # import requests
    # requests.adapters.TimeoutSauce = ItouTimeout
    # requests.get() # custom time out is applied

    """

    def __init__(self, *args, **kwargs):
        if kwargs["connect"] is None:
            kwargs["connect"] = REQUESTS_TIMEOUT_SECONDS
        if kwargs["read"] is None:
            kwargs["read"] = REQUESTS_TIMEOUT_SECONDS
        super().__init__(*args, **kwargs)


def itou_requests_config(func):
    def wrapper(*args, **kwargs):
        requests.adapters.TimeoutSauce = ItouTimeout
        func(*args, **kwargs)

    return wrapper
