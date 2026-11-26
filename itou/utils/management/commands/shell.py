import os

from django.core.management.commands import shell

from itou.utils import triggers
from itou.utils.command import TriggerContextMixin


def shell_context():
    return triggers.context(user=os.getenv("CC_USER_ID"))


class Command(TriggerContextMixin, shell.Command):
    AUTO_TRIGGER_CONTEXT = False

    def get_auto_imports(self):
        return super().get_auto_imports() + [
            "django.conf.settings",
            "django.utils.timezone",
            "datetime",
            "django.db.transaction",
            "itou.utils.management.commands.shell.shell_context",
        ]
