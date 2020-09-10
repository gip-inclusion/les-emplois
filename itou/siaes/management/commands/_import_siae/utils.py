"""

Various helpers for the import_siae.py script.

"""
from functools import wraps
from time import time


SHOW_IMPORT_SIAE_METHOD_TIMER = True


def timeit(f):
    """
    Quick and dirty method timer (as a decorator).
    Could not make it work easily with the `import_siae.Command` class.
    Thus dirty becauses uses `print` instead of `self.log`.
    """

    @wraps(f)
    def wrap(*args, **kw):
        ts = time()
        result = f(*args, **kw)
        te = time()
        msg = f"Method {f.__name__} took {te - ts:.2f} seconds to complete"
        if SHOW_IMPORT_SIAE_METHOD_TIMER:
            print(msg)
        return result

    return wrap
