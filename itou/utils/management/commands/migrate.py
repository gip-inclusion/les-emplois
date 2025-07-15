from django.core.management.commands import migrate

from itou.utils.command import LoggedCommandMixin
from itou.utils.db import lock_timeout, pg_advisory_lock, statement_timeout


class Command(LoggedCommandMixin, migrate.Command):
    def handle(self, *args, **kwargs):
        with statement_timeout(0), lock_timeout(0), pg_advisory_lock("migrate"):
            return super().handle(*args, **kwargs)
