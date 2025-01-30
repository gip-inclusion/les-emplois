import logging
from functools import wraps
from time import perf_counter


logger = logging.getLogger(__name__)


class Sentinel:
    """Class to be used for sentinel object, but the object will be falsy"""

    def __bool__(self):
        return False


def timeit(f):
    """
    Quick and dirty method timer (as a decorator).
    Could not make it work easily with the `import_siae.Command` class.
    Thus dirty becauses uses `print` instead of `self.log`.

    Maybe later we can use this builtin timer instead:
    https://docs.python.org/3/library/timeit.html#python-interface
    """

    @wraps(f)
    def wrap(*args, **kw):
        ts = perf_counter()
        result = f(*args, **kw)
        logger.info("timeit: method=%s completed in seconds=%.2f", f.__name__, perf_counter() - ts)
        return result

    return wrap
