from django.db import connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder

from itou.utils.command import BaseCommand


class Command(BaseCommand):
    """
    Clean old applied migrations after a migration squash
    """

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument("--wet-run", action="store_true")

    def handle(self, *, wet_run, **options):
        recorder = MigrationRecorder(connection)
        recorded_migrations = recorder.applied_migrations()
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        disk_migrations = loader.disk_migrations

        to_delete = sorted(set(recorded_migrations) - set(disk_migrations))
        self.logger.info(f"Deleting {len(to_delete)} old migrations from django_mirations table")
        for app, name in to_delete:
            migration = recorded_migrations[(app, name)]
            self.logger.info(f"  {app}.{name} applied={migration.applied.date()}")

        if wet_run:
            with transaction.atomic():
                for app, name in to_delete:
                    MigrationRecorder.Migration.objects.filter(app=app, name=name).delete()

        else:
            self.logger.info("Run with wet-run to really delete these migrations")
