import collections
import contextlib
import functools
import logging
import time
import uuid

from asgiref.local import Local  # NOQA
from django.core.management import base
from django.db import connection, transaction


local = Local()

CommandInfo = collections.namedtuple("CommandInfo", ["run_uid", "name", "wet_run"])


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
def _command_info_manager(command, *, wet_run=None):
    command_info_before = get_current_command_info()
    local.command_info = CommandInfo(str(command.run_uid), command.__class__.__module__, wet_run)
    try:
        yield
    finally:
        if command_info_before is None:
            del local.command_info
        else:
            local.command_info = command_info_before


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


def dry_runnable(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        wet_run = kwargs.get("wet_run")
        if wet_run is None:
            raise RuntimeError('No "wet_run" argument was given')

        command = args[0] if args and args[0] and isinstance(args[0], LoggedCommandMixin) else None
        command_info = _command_info_manager(args[0], wet_run=wet_run) if command else contextlib.nullcontext()

        with transaction.atomic(), command_info:
            if not wet_run and command:
                command.logger.info("Command launched with wet_run=%s", wet_run)
            func(*args, **kwargs)
            if not wet_run:
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE;")
                transaction.set_rollback(True)
                if command:
                    command.logger.info("Setting transaction to be rollback as wet_run=%s", wet_run)

    return wrapper
