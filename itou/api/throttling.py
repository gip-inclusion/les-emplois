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
