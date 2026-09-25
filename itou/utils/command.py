import contextlib
import os
import sys

from django.conf import settings
from django.core.cache import cache
from django.core.management import base
from itoutils.django.commands import AtomicHandleMixin, LoggedCommandMixin, get_current_command_info

from itou.utils import triggers
from itou.utils.enums import ItouEnvironment


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
    def execute(self, *args, **kwargs):

        try:
            command = sys.argv[1]
        except IndexError:
            if settings.ITOU_ENVIRONMENT == ItouEnvironment.TEST:
                # When running tests, `sys.argv` can be just  "pytest".
                command = "fake-name"
            else:
                raise
        cache_key = f"itou:executing-command:{command}"
        # `timeout`: We want the key to expire on its own if the
        # command crashes before we properly remove the key in the
        # `finally` clause below. The TTL does not have to be very
        # long (and not necessarily longer than the duration of the
        # command), just long enough that two instances won't be
        # executed simultaneously by two crontabs on two instances
        # during a deployment.
        #
        # `nx=True` Avoid race condition: when 2 commands are executed
        # at the same time, only the first one sets the key; the
        # second one will detect that the key has already been set.
        if not cache.set(cache_key, "marker", timeout=60, nx=True):
            self.logger.info(
                "Aborted concurrent execution of command %s",
                command,
            )
            return

        try:
            return super().execute(*args, **kwargs)
        finally:
            cache.delete(cache_key)

    def handle(self, *args, **options):
        raise NotImplementedError()
