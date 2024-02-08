import socket
from unittest import mock

from django.core.cache.backends.redis import RedisCacheClient

from itou.utils.cache import FAILSAFE_METHODS, FailSafeRedisCache


class TestFailSafeRedisCache:
    def test_access_with_bad_url(self, settings):
        with socket.create_server(("localhost", 0)) as s:
            empty_port = s.getsockname()[1]
            s.close()
            cache = FailSafeRedisCache(f"redis://localhost:{empty_port}", {})
            with mock.patch("itou.utils.cache.capture_exception") as sentry_mock:
                assert cache.get("foo") is None
            sentry_mock.assert_called_once()
            [args, kwargs] = sentry_mock.call_args
            [exception] = args
            assert exception.args == (f"Error 111 connecting to localhost:{empty_port}. Connection refused.",)
            assert kwargs == {}

    def test_known_public_methods(self):
        actual_keys = {k for k in RedisCacheClient.__dict__ if not k.startswith("_")}
        # Not a cache access.
        actual_keys.remove("get_client")
        assert actual_keys - FAILSAFE_METHODS == set()
