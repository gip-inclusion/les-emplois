import collections
import contextlib
import functools
import logging
import os
import time
import uuid

from asgiref.local import Local  # NOQA
from django.core.management import base
from django.db import connection, transaction

from itou.utils import triggers


local = Local()

CommandInfo = collections.namedtuple("CommandInfo", ["run_uid", "name", "wet_run"])


def get_current_command_info():
    return getattr(local, "command_info", None)


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
    run_uid = command_info_before.run_uid if command_info_before else str(uuid.uuid4())
    local.command_info = CommandInfo(run_uid, command.__class__.__module__, wet_run)
    try:
        yield local.command_info
    finally:
        local.command_info = command_info_before


class LoggedCommandMixin:
    ATOMIC_HANDLE = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self.__class__.__module__)

    def execute(self, *args, **kwargs):
        with contextlib.ExitStack() as stack:
            command_info = stack.enter_context(_command_info_manager(self, wet_run=kwargs.get("wet_run")))
            stack.enter_context(_command_duration_logger(self))
            if self.ATOMIC_HANDLE:
                stack.enter_context(transaction.atomic())
            stack.enter_context(triggers.context(user=os.getenv("CC_USER_ID"), run_uid=command_info.run_uid))
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

        logger = (
            args[0].logger
            if args and args[0] and isinstance(args[0], LoggedCommandMixin)
            else logging.getLogger(func.__module__)
        )
        with transaction.atomic():
            if not wet_run:
                logger.info("Command launched with wet_run=%s", wet_run)
            func(*args, **kwargs)
            if not wet_run:
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE;")
                transaction.set_rollback(True)
                logger.info("Setting transaction to be rollback as wet_run=%s", wet_run)

    return wrapper
