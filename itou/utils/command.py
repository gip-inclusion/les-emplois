import os

from django.core.management import base
from itoutils.django.commands import AtomicHandleMixin, LoggedCommandMixin, get_current_command_info

from itou.utils import triggers


class TriggerContextMixin:
    def execute(self, *args, **kwargs):
        with triggers.context(user=os.getenv("CC_USER_ID"), run_uid=get_current_command_info().run_uid):
            return super().execute(*args, **kwargs)


class BaseCommand(LoggedCommandMixin, AtomicHandleMixin, TriggerContextMixin, base.BaseCommand):
    def handle(self, *args, **options):
        raise NotImplementedError()
