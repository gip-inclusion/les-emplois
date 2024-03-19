from functools import wraps

from django.core.cache.backends.redis import RedisCache, RedisCacheClient
from redis import exceptions as redis_exceptions
from sentry_sdk.api import capture_exception


IGNORED_EXCEPTIONS = (
    OSError,
    redis_exceptions.ConnectionError,
    redis_exceptions.ResponseError,
    redis_exceptions.TimeoutError,
)


FAILSAFE_METHODS = frozenset(
    (
        "add",
        "get",
        "set",
        "touch",
        "delete",
        "get_many",
        "has_key",
        "incr",
        "set_many",
        "delete_many",
        "clear",
    )
)


class FailSafeRedisCacheClient(RedisCacheClient):
    def __getattribute__(self, name):
        attr_or_meth = super().__getattribute__(name)
        if name in FAILSAFE_METHODS:

            @wraps(attr_or_meth)
            def report_failure(*args, **kwargs):
                try:
                    return attr_or_meth(*args, **kwargs)
                except IGNORED_EXCEPTIONS as e:
                    capture_exception(e)
                    # None is the return for a GET where the key does not exist.
                    return None

            return report_failure
        return attr_or_meth


class FailSafeRedisCache(RedisCache):
    def __init__(self, server, params):
        super().__init__(server, params)
        self._class = FailSafeRedisCacheClient

    def clear(self):
        # RedisCache calls FLUSHDB, which is not concerned with KEY_PREFIX.
        # That’s an issue for tests isolation.
        raise RuntimeError("Don’t clear the cache.")


class UnclearableCache(RedisCache):
    def clear(self):
        # RedisCache calls FLUSHDB, which is not concerned with KEY_PREFIX.
        # That’s an issue for tests isolation.
        raise RuntimeError("Don’t clear the cache.")
