from django.core.cache import caches
from rest_framework import throttling


class FailSafeMixin(throttling.BaseThrottle):
    @property
    def cache(self):
        # The property allows swapping cache configuration in tests.
        return caches["failsafe"]


class FailSafeSimpleRateThrottle(FailSafeMixin, throttling.SimpleRateThrottle):
    """Like DRF's SimpleRateThrottle but using our failsafe cache."""


class FailSafeAnonRateThrottle(FailSafeMixin, throttling.AnonRateThrottle):
    """Like DRF's AnonRateThrottle but using our failsafe cache."""


class FailSafeUserRateThrottle(FailSafeMixin, throttling.UserRateThrottle):
    """Like DRF's UserRateThrottle but using our failsafe cache."""
