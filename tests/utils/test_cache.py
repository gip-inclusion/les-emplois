import re
from unittest import mock

from django.core.cache.backends.redis import RedisCacheClient

from itou.utils.cache import FAILSAFE_METHODS


class TestFailSafeRedisCache:
    def test_access_with_bad_url(self, settings, failing_cache):
        with mock.patch("itou.utils.cache.capture_exception") as sentry_mock:
            assert failing_cache.get("foo") is None
        sentry_mock.assert_called_once()
        [args, kwargs] = sentry_mock.call_args
        [exception] = args
        # django-redis chains redis original exceptions through ConnectionInterrupted
        [exc_msg] = exception.__cause__.args if exception.__cause__ else exception.args
        # Message error code depends on the platform (Mac or Linux). Should be a variation of the following ones:
        # Error 99 connecting to localhost:{empty_port}. Cannot assign requested address.
        # Error 111 connecting to localhost:{empty_port}. Connection refused.
        assert re.match(r"Error \d+ connecting to localhost", exc_msg)
        assert kwargs == {}

    def test_known_public_methods(self):
        actual_keys = {k for k in RedisCacheClient.__dict__ if not k.startswith("_")}
        # Not a cache access.
        actual_keys.remove("get_client")
        assert actual_keys - FAILSAFE_METHODS == set()
