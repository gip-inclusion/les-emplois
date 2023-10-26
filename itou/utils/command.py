import contextlib
import logging
import time

from django.core.management import base


def _log_command_result(command, duration_in_ns, result):
    command.logger.info(
        f"Management command %s {result} in %0.2f seconds",
        command.__module__,
        duration_in_ns / 1_000_000_000,
        extra={
            "command": command.__module__,
            # Datadog expects duration in ns
            "duration": duration_in_ns,
        },
    )


@contextlib.contextmanager
def _command_duration_logger(command):
    before = time.perf_counter_ns()
    try:
        yield
    except Exception:
        _log_command_result(command, time.perf_counter_ns() - before, "failed")
        raise
    _log_command_result(command, time.perf_counter_ns() - before, "succeeded")


class LoggedCommandMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self.__class__.__module__)

    def execute(self, *args, **kwargs):
        with _command_duration_logger(self):
            try:
                return super().execute(*args, **kwargs)
            except Exception:
                self.logger.exception(
                    "Error when executing %s",
                    self.__module__,
                    extra={
                        "command": self.__module__,
                    },
                )
                raise


class BaseCommand(LoggedCommandMixin, base.BaseCommand):
    def handle(self, *args, **options):
        raise NotImplementedError()
