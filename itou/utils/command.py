import collections
import contextlib
import logging
import time
import uuid

from asgiref.local import Local  # NOQA
from django.core.management import base


local = Local()

CommandInfo = collections.namedtuple("CommandInfo", ["run_uid", "name"])


def get_current_command_info():
    try:
        return local.command_info
    except AttributeError:
        return None


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


@contextlib.contextmanager
def _command_info_manager(command):
    command_info_before = get_current_command_info()
    if command_info_before is None:
        local.command_info = CommandInfo(str(command.run_uid), command.__class__.__module__)
    try:
        yield
    finally:
        if command_info_before is None:
            del local.command_info


class LoggedCommandMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.run_uid = uuid.uuid4()
        self.logger = logging.getLogger(self.__class__.__module__)

    def execute(self, *args, **kwargs):
        with _command_info_manager(self), _command_duration_logger(self):
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
