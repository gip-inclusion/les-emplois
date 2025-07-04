from django.core.cache import caches
from rest_framework import throttling


class FailSafeAnonRateThrottle(throttling.AnonRateThrottle):
    rate = "30/minute"

    @property
    def cache(self):
        # The property allows swapping cache configuration in tests.
        return caches["failsafe"]


class FailSafeUserRateThrottle(throttling.UserRateThrottle):
    rate = "60/minute"

    @property
    def cache(self):
        # The property allows swapping cache configuration in tests.
        return caches["failsafe"]
