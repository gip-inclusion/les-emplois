import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from django.core.management import call_command
from django.db import connection


# Any command would do, as long as it inherits from `BaseCommand`.
def test_simultaneous_run_is_aborted():
    runs = []
    barrier = threading.Barrier(2)

    def mocked_handle(*args, **kwargs):
        # Make the processing slow enough that a second run can be
        # simultaneous.
        time.sleep(0.5)
        runs.append(1)

    def run_command():
        barrier.wait(timeout=1)

        try:
            with mock.patch(
                "itou.users.management.commands.archive_old_assignments.Command.handle",
                mocked_handle,
            ):
                call_command("archive_old_assignments")
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        run1 = executor.submit(run_command)
        run2 = executor.submit(run_command)

        run1.result(timeout=2)
        run2.result(timeout=2)

    assert len(runs) == 1
