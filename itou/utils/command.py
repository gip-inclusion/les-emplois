import collections
import contextlib
import logging
import os
import time
import uuid

from asgiref.local import Local  # NOQA
from django.core.management import base
from django.db import transaction

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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self.__class__.__module__)

    def execute(self, *args, **kwargs):
        with _command_info_manager(self, wet_run=kwargs.get("wet_run")), _command_duration_logger(self):
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


class AtomicHandleMixin:
    ATOMIC_HANDLE = False

    def execute(self, *args, **kwargs):
        with transaction.atomic() if self.ATOMIC_HANDLE else contextlib.nullcontext():
            return super().execute(*args, **kwargs)


class TriggerContextMixin:
    def execute(self, *args, **kwargs):
        with triggers.context(user=os.getenv("CC_USER_ID"), run_uid=get_current_command_info().run_uid):
            return super().execute(*args, **kwargs)


class BaseCommand(LoggedCommandMixin, AtomicHandleMixin, TriggerContextMixin, base.BaseCommand):
    def handle(self, *args, **options):
        raise NotImplementedError()
