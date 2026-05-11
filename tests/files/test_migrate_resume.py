import datetime

import pytest
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.management.base import CommandError

from itou.files.models import File
from tests.files.factories import FileFactory
from tests.utils.testing import default_storage_ls_files


@pytest.mark.usefixtures("temporary_bucket")
def test_migrate_resume_to_private(pdf_file, mocker):
    # Make every just-uploaded legacy object eligible for migration
    # by setting the retention to a negative value
    mocker.patch(
        "itou.files.management.commands.migrate_resume_to_private.LEGACY_RETENTION",
        datetime.timedelta(days=-1),
    )

    legacy_key = "resume/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.pdf"
    default_storage.save(legacy_key, pdf_file)
    legacy_file = FileFactory(key=legacy_key)

    already_migrated_key = "resume-private/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb.pdf"
    default_storage.save(already_migrated_key, pdf_file)
    already_migrated = FileFactory(key=already_migrated_key)

    call_command("migrate_resume_to_private", "--wet-run")

    legacy_file.refresh_from_db()
    assert legacy_file.key == "resume-private/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.pdf"

    already_migrated.refresh_from_db()
    assert already_migrated.key == already_migrated_key

    # Both copies now exist: the private one for future reads & the legacy one for
    # already-sent URLs still in the wild.
    assert set(default_storage_ls_files()) == {
        legacy_key,
        "resume-private/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.pdf",
        already_migrated_key,
    }

    # Idempotent: a second run rekeys nothing more (DB already updated, destination exists).
    call_command("migrate_resume_to_private", "--wet-run")
    legacy_file.refresh_from_db()
    assert legacy_file.key == "resume-private/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.pdf"


@pytest.mark.usefixtures("temporary_bucket")
def test_migrate_resume_to_private_dry_run_by_default(pdf_file, mocker):
    mocker.patch(
        "itou.files.management.commands.migrate_resume_to_private.LEGACY_RETENTION",
        datetime.timedelta(days=-1),
    )

    legacy_key = "resume/cccccccc-cccc-cccc-cccc-cccccccccccc.pdf"
    default_storage.save(legacy_key, pdf_file)
    legacy_file = FileFactory(key=legacy_key)

    call_command("migrate_resume_to_private")

    legacy_file.refresh_from_db()
    assert legacy_file.key == legacy_key
    assert default_storage_ls_files() == [legacy_key]


@pytest.mark.usefixtures("temporary_bucket")
def test_migrate_resume_to_private_logs_an_error_when_destination_row_exists(pdf_file, mocker, caplog):
    # Both S3 sides exist and a File row already references the destination key:
    # rekeying the source row would violate File.key's unique constraint, so the command
    # must skip and log an error.
    mocker.patch(
        "itou.files.management.commands.migrate_resume_to_private.LEGACY_RETENTION",
        datetime.timedelta(days=-1),
    )

    legacy_key = "resume/eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee.pdf"
    new_key = "resume-private/eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee.pdf"
    default_storage.save(legacy_key, pdf_file)
    default_storage.save(new_key, pdf_file)
    legacy_file = FileFactory(key=legacy_key)
    colliding_file = FileFactory(key=new_key)

    call_command("migrate_resume_to_private", "--wet-run")

    legacy_file.refresh_from_db()
    assert legacy_file.key == legacy_key
    colliding_file.refresh_from_db()
    assert colliding_file.key == new_key
    assert any(
        "another File row already uses" in record.message and record.levelname == "ERROR" for record in caplog.records
    )


@pytest.mark.usefixtures("temporary_bucket")
def test_migrate_resume_to_private_skips_recent(pdf_file):
    # With the default 90-day retention, a freshly uploaded object stays under `resume/`
    # so that public URLs in the wild keep resolving.
    legacy_key = "resume/dddddddd-dddd-dddd-dddd-dddddddddddd.pdf"
    default_storage.save(legacy_key, pdf_file)
    legacy_file = FileFactory(key=legacy_key)

    call_command("migrate_resume_to_private", "--wet-run")

    legacy_file.refresh_from_db()
    assert legacy_file.key == legacy_key
    assert default_storage_ls_files() == [legacy_key]


@pytest.mark.empty_temporary_bucket_expected
@pytest.mark.usefixtures("temporary_bucket")
def test_migrate_resume_to_private_raises_when_empty():
    # Empty `resume/` prefix means migration is over: signal it loudly so the cron entry
    # and the command itself can be removed.
    with pytest.raises(CommandError, match="resume/ is empty"):
        call_command("migrate_resume_to_private", "--wet-run")


@pytest.mark.usefixtures("temporary_bucket")
def test_migrate_resume_to_private_stops_when_time_budget_exhausted(pdf_file, mocker, caplog):
    # With a zero-minute budget, the deadline is reached on the very first object: the loop
    # exits before touching S3, the warning is emitted, and no CommandError is raised even
    # though `listed == 0`.
    mocker.patch(
        "itou.files.management.commands.migrate_resume_to_private.LEGACY_RETENTION",
        datetime.timedelta(days=-1),
    )
    legacy_key = "resume/ffffffff-ffff-ffff-ffff-ffffffffffff.pdf"
    default_storage.save(legacy_key, pdf_file)
    legacy_file = FileFactory(key=legacy_key)

    call_command("migrate_resume_to_private", "--wet-run", "--max-runtime-minutes=0")

    legacy_file.refresh_from_db()
    assert legacy_file.key == legacy_key
    assert any("time budget exhausted" in record.message and record.levelname == "INFO" for record in caplog.records)


@pytest.mark.usefixtures("temporary_bucket")
def test_migrate_resume_to_private_logs_avg_per_object_after_partial_run(pdf_file, mocker, caplog):
    mocker.patch(
        "itou.files.management.commands.migrate_resume_to_private.LEGACY_RETENTION",
        datetime.timedelta(days=-1),
    )
    legacy_keys = [f"resume/aaaaaaaa-aaaa-aaaa-aaaa-00000000000{i}.pdf" for i in range(3)]
    for key in legacy_keys:
        default_storage.save(key, pdf_file)
        FileFactory(key=key)

    # monotonic sequence:
    #   1. started_at = 0
    #   2. first object  → 1   (< deadline=60, processed)
    #   3. second object → 70  (>= deadline, break)
    #   4. elapsed read  → 71
    mocker.patch(
        "itou.files.management.commands.migrate_resume_to_private.monotonic",
        side_effect=iter([0, 1, 70, 71, 72]),
    )

    call_command("migrate_resume_to_private", "--wet-run", "--max-runtime-minutes=1")

    assert File.objects.filter(key__startswith="resume-private/").count() == 1
    assert File.objects.filter(key__startswith="resume/").exclude(key__startswith="resume-private/").count() == 2
    info = next(
        record for record in caplog.records if record.levelname == "INFO" and "time budget exhausted" in record.message
    )
    assert "listed=3" in info.message
    assert "eligible=3" in info.message
    assert "copied=1" in info.message
    assert "avg_per_object=" in info.message


@pytest.mark.usefixtures("temporary_bucket")
def test_migrate_resume_to_private_uses_setting_when_arg_omitted(pdf_file, mocker, caplog, settings):
    mocker.patch(
        "itou.files.management.commands.migrate_resume_to_private.LEGACY_RETENTION",
        datetime.timedelta(days=-1),
    )
    settings.MIGRATE_RESUME_MAX_RUNTIME_MINUTES = 0

    legacy_key = "resume/99999999-9999-9999-9999-999999999999.pdf"
    default_storage.save(legacy_key, pdf_file)
    legacy_file = FileFactory(key=legacy_key)

    call_command("migrate_resume_to_private", "--wet-run")

    legacy_file.refresh_from_db()
    assert legacy_file.key == legacy_key
    assert any("time budget exhausted" in record.message for record in caplog.records)
