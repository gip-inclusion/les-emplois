import contextlib
import time

from asgiref.local import Local  # NOQA


local = Local()


def reinit():
    local.sql_timing = 0.0


def get_current_timing_info():
    try:
        return local.sql_timing
    except AttributeError:
        return None


@contextlib.contextmanager
def timing():
    start = time.perf_counter()
    yield
    timing = getattr(local, "sql_timing", 0)
    # Store in nanoseconds like all datadog durations
    local.sql_timing = timing + 1_000_000_000 * (time.perf_counter() - start)
