from functools import wraps

from django_redis.cache import CONNECTION_INTERRUPTED, RedisCache
from django_redis.client import DefaultClient
from django_redis.exceptions import ConnectionInterrupted
from redis import exceptions as redis_exceptions
from sentry_sdk.api import capture_exception


IGNORED_EXCEPTIONS = (
    OSError,
    ConnectionInterrupted,
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


class FailSafeRedisCacheClient(DefaultClient):
    def __getattribute__(self, name):
        attr_or_meth = super().__getattribute__(name)
        if name in FAILSAFE_METHODS:

            @wraps(attr_or_meth)
            def report_failure(*args, **kwargs):
                try:
                    return attr_or_meth(*args, **kwargs)
                except IGNORED_EXCEPTIONS as e:
                    capture_exception(e)
                    return CONNECTION_INTERRUPTED  # return for a GET where the key does not exist.

            return report_failure
        return attr_or_meth


class UnclearableCache(RedisCache):
    def clear(self):
        # RedisCache calls FLUSHDB, which is not concerned with KEY_PREFIX.
        # That’s an issue for tests isolation.
        raise RuntimeError("Don’t clear the cache.")
