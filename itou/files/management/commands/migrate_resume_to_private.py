import datetime
from time import monotonic

from django.conf import settings
from django.core.management.base import CommandError
from django.utils import timezone

from itou.files.models import File
from itou.utils.command import BaseCommand
from itou.utils.storage.s3 import s3_client


LEGACY_PREFIX = "resume/"
PRIVATE_PREFIX = "resume-private/"
LEGACY_RETENTION = datetime.timedelta(days=90)


class Command(BaseCommand):
    """Migrate aged-out legacy `resume/` S3 objects into the private `resume-private/` prefix.

    List every object under `resume/` and migrate the ones whose `LastModified` is older than
    `LEGACY_RETENTION`. Recent objects are left in place so that public URLs still circulating
    in emails / cached API responses keep resolving.

    For each aged object:
    - The object is copied server-side on S3 to `resume-private/<same-basename>`.
    - The matching `File.key` column is updated to the new key.
    - The legacy object is left in place and once the row no longer references it,
      `delete_unused_files` will reap it as an orphan after its own ``CLEANING_DELAY``.

    Designed to run daily. When `resume/` becomes empty the command raises so that we know
    the migration is over and the command + its cron entry can be removed.

    Idempotent: if the destination already exists, only the DB row is rekeyed.
    """

    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    def add_arguments(self, parser):
        parser.add_argument(
            "--wet-run",
            dest="wet_run",
            action="store_true",
            help="Actually perform the S3 copies and DB updates. Without it, the command is a dry run.",
        )
        parser.add_argument(
            "--max-runtime-minutes",
            dest="max_runtime_minutes",
            type=int,
            default=None,
            help=(
                "Stop after this many minutes of wall-clock time. "
                "Defaults to settings.MIGRATE_RESUME_MAX_RUNTIME_MINUTES "
                "(env var MIGRATE_RESUME_MAX_RUNTIME_MINUTES, default 60)."
            ),
        )

    def handle(self, *, wet_run, max_runtime_minutes, **options):
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        client = s3_client()
        cutoff = timezone.now() - LEGACY_RETENTION

        if max_runtime_minutes is None:
            max_runtime_minutes = settings.MIGRATE_RESUME_MAX_RUNTIME_MINUTES
        started_at = monotonic()
        deadline = started_at + max_runtime_minutes * 60
        stopped_due_to_time_budget = False

        listed = 0
        eligible = 0
        copied = 0
        errors = 0

        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=LEGACY_PREFIX):
            for obj_summary in page.get("Contents", []):
                listed += 1
                if obj_summary["LastModified"] >= cutoff:
                    continue
                eligible += 1
                if stopped_due_to_time_budget or monotonic() >= deadline:
                    stopped_due_to_time_budget = True
                    continue
                old_key = obj_summary["Key"]
                new_key = PRIVATE_PREFIX + old_key[len(LEGACY_PREFIX) :]

                file = File.objects.filter(key=old_key).first()
                if file is None:
                    continue  # Orphan on S3 side, the cron `delete_unused_files` will reap it

                try:
                    client.head_object(Bucket=bucket, Key=new_key)
                except client.exceptions.ClientError as head_object_exc:
                    if head_object_exc.response["Error"]["Code"] not in {"404", "NoSuchKey", "NotFound"}:
                        # If the file simply doesn't exist, that's expected because it hasn't been copied yet,
                        # but if the error is something else (like permission denied), we record it and skip this file
                        errors += 1
                        self.logger.exception(
                            "migrate_resume_to_private: head_object failed for %s: %s",
                            new_key,
                            head_object_exc,
                        )
                        continue
                else:  # Destination already exists on S3, that should not happen
                    errors += 1
                    if File.objects.filter(key=new_key).exists():
                        # A File row already references `new_key`: rekeying source would violate the
                        # unique constraint on File.key
                        self.logger.error(
                            "migrate_resume_to_private: cannot rekey File %s from %s to %s, "
                            "another File row already uses %s",
                            file.pk,
                            old_key,
                            new_key,
                            new_key,
                        )
                    else:  # No `File` row points to the source row's location yet
                        self.logger.error(
                            "migrate_resume_to_private: destination %s already exists on S3 with no "
                            "matching File row, rekeying File %s (S3 copy skipped)%s",
                            new_key,
                            file.pk,
                            "" if wet_run else " [dry run]",
                        )
                        if wet_run:
                            File.objects.filter(pk=file.pk, key=old_key).update(key=new_key)
                    continue

                if not wet_run:
                    self.logger.info(
                        "[dry run] would copy s3://%s/%s -> s3://%s/%s and rekey File %s",
                        bucket,
                        old_key,
                        bucket,
                        new_key,
                        file.pk,
                    )
                    continue

                try:
                    client.copy_object(
                        Bucket=bucket,
                        Key=new_key,
                        CopySource={"Bucket": bucket, "Key": old_key},
                    )
                except client.exceptions.ClientError as copy_object_exc:
                    errors += 1
                    self.logger.exception(
                        "migrate_resume_to_private: copy failed for %s: %s",
                        old_key,
                        copy_object_exc,
                    )
                    continue

                updated = File.objects.filter(pk=file.pk, key=old_key).update(key=new_key)
                if updated == 0:
                    self.logger.warning(
                        "migrate_resume_to_private: file %s key changed by another process, leaving %s in place",
                        file.pk,
                        new_key,
                    )
                copied += 1

        elapsed = monotonic() - started_at
        avg_ms = (elapsed * 1000 / listed) if listed else 0.0
        self.logger.info(
            "migrate_resume_to_private: %s; listed=%d eligible=%d copied=%d errors=%d avg_per_object=%.1fms",
            "time budget exhausted" if stopped_due_to_time_budget else "done",
            listed,
            eligible,
            copied,
            errors,
            avg_ms,
        )

        if listed == 0 and not stopped_due_to_time_budget:
            raise CommandError(
                f"migrate_resume_to_private: {LEGACY_PREFIX} is empty, migration complete: "
                "revert the commit that added this command."
            )
