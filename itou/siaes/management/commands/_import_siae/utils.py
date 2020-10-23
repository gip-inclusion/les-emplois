"""

Various helpers for the import_siae.py script.

"""
from functools import wraps
from time import time


SHOW_IMPORT_SIAE_METHOD_TIMER = False


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
        if SHOW_IMPORT_SIAE_METHOD_TIMER:
            print(msg)
        return result

    return wrap


def remap_columns(df, column_mapping):
    """
    Rename columns according to mapping and delete all other columns.

    Example of column_mapping :

    {"ID Structure": "asp_id", "Adresse e-mail": "auth_email"}
    """
    df.rename(
        columns=column_mapping, inplace=True,
    )

    # Keep only the columns we need.
    df = df[column_mapping.values()]

    return df
