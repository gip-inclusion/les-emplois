import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from django.core.management import call_command
from django.db import connection


def test_simultaneous_run_is_aborted():
    command_runs = []

    timeout = 1

    barrier = threading.Barrier(parties=2, timeout=timeout)
    first_thread_started_command = threading.Event()
    second_thread_ended_command = threading.Event()

    def mocked_handle(*args, **kwargs):
        # Notify second thread that it can call `call_command`.
        first_thread_started_command.set()
        command_runs.append(1)
        # The goal here is to run for long enough, to make sure that
        # the second thread ran `call_command` while the first thread
        # was still running it.
        assert second_thread_ended_command.wait(timeout)

    def run_command():
        thread_position = barrier.wait()
        this_is_the_second_thread = thread_position == 1  # 0 would be the 1st thread
        try:
            # Make sure that the second thread does not call the
            # command before the first one is running the command.
            if this_is_the_second_thread:
                assert first_thread_started_command.wait(timeout)

            with mock.patch(
                "itou.users.management.commands.archive_old_assignments.Command.handle",
                mocked_handle,
            ):
                # Any command would do, as long as it inherits from `BaseCommand`.
                call_command("archive_old_assignments")
        finally:
            if this_is_the_second_thread:
                # Notify the first thread that it can exit from our
                # `mocked_handle()`.
                second_thread_ended_command.set()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        run1 = executor.submit(run_command)
        run2 = executor.submit(run_command)
        run1.result(timeout=2)
        run2.result(timeout=2)

    assert len(command_runs) == 1
