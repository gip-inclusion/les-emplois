from django.contrib.humanize.templatetags.humanize import apnumber
from django.core.cache import caches
from rest_framework import throttling


class FailSafeAnonRateThrottle(throttling.AnonRateThrottle):
    @property
    def cache(self):
        # The property allows swapping cache configuration in tests.
        return caches["failsafe"]


class FailSafeUserRateThrottle(throttling.UserRateThrottle):
    @property
    def cache(self):
        # The property allows swapping cache configuration in tests.
        return caches["failsafe"]

    def french_rate_limit(self, rate):
        if rate is None:
            return ""
        num, period = rate.split("/")
        num_requests = int(num)
        french_period = {"s": "seconde", "m": "minute", "h": "heure", "d": "jour"}[period[0]]
        return f"{apnumber(num_requests)} par {french_period}"
