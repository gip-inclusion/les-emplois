from django.core.cache import caches
from rest_framework import throttling

from itou.utils.auth import get_client_ip


class GetClientIPMixin(throttling.BaseThrottle):
    """Replaces the get_ident provided by BaseThrottle by a version
    that uses our get_client_ip() which is more robust in the
    CleverCloud network (by using CC_REVERSE_PROXY_IPS).
    """

    def get_ident(self, request):
        return get_client_ip(request)


class FailSafeMixin(throttling.BaseThrottle):
    @property
    def cache(self):
        # The property allows swapping cache configuration in tests.
        return caches["failsafe"]


class FailSafeSimpleRateThrottle(GetClientIPMixin, FailSafeMixin, throttling.SimpleRateThrottle):
    """Like DRF's SimpleRateThrottle but using our failsafe cache."""


class FailSafeAnonRateThrottle(GetClientIPMixin, FailSafeMixin, throttling.AnonRateThrottle):
    """Like DRF's AnonRateThrottle but using our failsafe cache."""


class FailSafeUserRateThrottle(GetClientIPMixin, FailSafeMixin, throttling.UserRateThrottle):
    """Like DRF's UserRateThrottle but using our failsafe cache."""
