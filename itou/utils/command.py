import contextlib
import os

from django.core.management import base
from itoutils.django.commands import AtomicHandleMixin, LoggedCommandMixin, get_current_command_info

from itou.utils import triggers
from itou.utils.db import CannotAcquireLock, pg_advisory_lock


class TriggerContextMixin:
    AUTO_TRIGGER_CONTEXT = True

    def get_trigger_context(self):
        return {"user": os.getenv("CC_USER_ID"), "run_uid": get_current_command_info().run_uid}

    def execute(self, *args, **kwargs):
        with (
            triggers.connection_wrapper(),
            triggers.context(**self.get_trigger_context()) if self.AUTO_TRIGGER_CONTEXT else contextlib.nullcontext(),
        ):
            return super().execute(*args, **kwargs)


class BaseCommand(LoggedCommandMixin, AtomicHandleMixin, TriggerContextMixin, base.BaseCommand):
    requires_system_checks = ()

    def execute(self, *args, **kwargs):
        # This session-level lock will be released when the command
        # ends. This avoids two instances of the command to run at the
        # same time (causing issues), which happens when two instances
        # of the code are live (during a deployment) and two cronjobs
        # are executed simultaneously.
        command = str(self.__module__)
        try:
            with pg_advisory_lock(f"command:{command}", wait=False, release=False):
                pass
        except CannotAcquireLock:
            self.logger.warning(
                "Aborted command %s because the command is already running",
                command,
            )
            return
        return super().execute(*args, **kwargs)

    def handle(self, *args, **options):
        raise NotImplementedError()
