from django.core.management.commands import shell

from itou.utils.command import TriggerContextMixin


class Command(TriggerContextMixin, shell.Command):
    AUTO_TRIGGER_CONTEXT = False

    def get_auto_imports(self):
        return super().get_auto_imports() + [
            "django.conf.settings",
            "django.utils.timezone",
            "datetime",
        ]
