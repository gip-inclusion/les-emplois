from functools import wraps
from time import time


DISPLAY_TIMER = True


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
        ts = time()
        result = f(*args, **kw)
        te = time()
        msg = f"Method {f.__name__} took {te - ts:.2f} seconds to complete"
        if DISPLAY_TIMER:
            print(msg)
        return result

    return wrap
