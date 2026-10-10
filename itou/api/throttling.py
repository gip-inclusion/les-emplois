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

    def is_throttled(self, request, view):
        """Returns True when the user is currently throttled, False otherwise.

        Beware of TOCTOU, this helper is for informative purposes, the decision
        about allowing a request MUST always come from allow_request().

        Inspired by SimpleRateThrottle.allow_request, but peeks at history
        entries.
        """
        self.key = self.get_cache_key(request, view)
        self.history = self.cache.get(self.key, [])
        self.now = self.timer()
        active_history_entries = [entry for entry in self.history if entry > self.now - self.duration]
        return len(active_history_entries) >= self.num_requests
