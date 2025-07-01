from django.core.management import call_command
from django.db.migrations.recorder import MigrationRecorder


def test_command(caplog):
    initial_count = MigrationRecorder.Migration.objects.count()

    migration = MigrationRecorder.Migration.objects.create(app="app_name", name="0011_old_migration")
    assert MigrationRecorder.Migration.objects.count() == initial_count + 1

    call_command("clean_old_applied_migrations")
    assert caplog.messages[:-1] == [
        "Deleting 1 old migrations from django_mirations table",
        f"  app_name.0011_old_migration applied={migration.applied.date()}",
        "Run with wet-run to really delete these migrations",
    ]
    assert MigrationRecorder.Migration.objects.count() == initial_count + 1
    assert MigrationRecorder.Migration.objects.filter(app="app_name", name="0011_old_migration").exists()

    caplog.clear()
    call_command("clean_old_applied_migrations", wet_run=True)
    assert caplog.messages[:-1] == [
        "Deleting 1 old migrations from django_mirations table",
        f"  app_name.0011_old_migration applied={migration.applied.date()}",
    ]
    assert MigrationRecorder.Migration.objects.count() == initial_count
    assert not MigrationRecorder.Migration.objects.filter(app="app_name", name="0011_old_migration").exists()

    caplog.clear()
    call_command("clean_old_applied_migrations", wet_run=True)
    assert caplog.messages[:-1] == ["Deleting 0 old migrations from django_mirations table"]
    assert MigrationRecorder.Migration.objects.count() == initial_count
    assert not MigrationRecorder.Migration.objects.filter(app="app_name", name="0011_old_migration").exists()
