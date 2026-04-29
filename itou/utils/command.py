import contextlib
import os

from django.core.management import base
from django.db import connection
from itoutils.django.commands import AtomicHandleMixin, LoggedCommandMixin, get_current_command_info

from itou.utils import triggers


class TriggerContextMixin:
    AUTO_TRIGGER_CONTEXT = True

    def get_trigger_context(self):
        return {"user": os.getenv("CC_USER_ID"), "run_uid": get_current_command_info().run_uid}

    def execute(self, *args, **kwargs):
        with (
            connection.execute_wrapper(triggers._set_context_connection_wrapper),
            triggers.context(**self.get_trigger_context()) if self.AUTO_TRIGGER_CONTEXT else contextlib.nullcontext(),
        ):
            return super().execute(*args, **kwargs)


class BaseCommand(LoggedCommandMixin, AtomicHandleMixin, TriggerContextMixin, base.BaseCommand):
    def handle(self, *args, **options):
        raise NotImplementedError()
