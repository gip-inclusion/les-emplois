import contextlib

from django.db import migrations

from itou.utils import triggers


class TriggerContextMigration(migrations.Migration):
    """
    Migration providing a triggers context, like `itou.utils.command.BaseCommand`.

    Non-atomic migrations must set `AUTO_TRIGGER_CONTEXT = False` and wrap each
    transaction in `triggers.context(migration="users.00xx...")`.
    """

    AUTO_TRIGGER_CONTEXT = True

    def get_trigger_context(self):
        return {"migration": f"{self.app_label}.{self.name}"}

    def apply(self, project_state, schema_editor, collect_sql=False):
        with (
            triggers.connection_wrapper(),
            triggers.context(**self.get_trigger_context()) if self.AUTO_TRIGGER_CONTEXT else contextlib.nullcontext(),
        ):
            return super().apply(project_state, schema_editor, collect_sql)
