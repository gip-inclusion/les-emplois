from django.core.management.commands import migrate

from itou.utils.command import LoggedCommandMixin
from itou.utils.db import pg_advisory_lock


class Command(LoggedCommandMixin, migrate.Command):
    def handle(self, *args, **kwargs):
        self.logger.info("Acquiring advisory lock for migrations.")
        with pg_advisory_lock("migrate"):
            return super().handle(*args, **kwargs)
