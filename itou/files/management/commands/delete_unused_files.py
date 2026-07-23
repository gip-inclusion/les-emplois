import datetime
import functools
import operator
from itertools import batched

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from itou.antivirus.models import Scan
from itou.files.models import File
from itou.utils.command import BaseCommand
from itou.utils.storage.s3 import TEMPORARY_STORAGE_PREFIX, s3_client


# Wait a bit before deleting a unknown file from S3 in case the database File is still not commited
# Also Wait a bit before deleting a orphan File since it might have ben created outside an atomic transation
CLEANING_DELAY = datetime.timedelta(days=1)


class Command(BaseCommand):
    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    def get_relations(self):
        relations = {
            (remote_field.field.model, remote_field.field.name)
            for remote_field in File._meta.get_fields(include_hidden=True)
            if remote_field.is_relation
        }
        relations.remove((Scan, "file"))
        return relations

    @transaction.atomic
    def delete_orphan_files(self):
        linked_files_pks = functools.reduce(
            operator.or_,
            [
                set(model.objects.exclude(**{field: None}).values_list(field, flat=True))
                for model, field in self.get_relations()
            ],
        )
        _deletions, deletions_per_type = (
            File.objects.filter(last_modified__lte=timezone.now() - CLEANING_DELAY)
            .exclude(pk__in=linked_files_pks)
            .delete()
        )
        self.logger.info(f"Deleted {deletions_per_type.get('files.File', 0)} orphans files from database")

    def clean_s3(self):
        client = s3_client()
        cutoff = timezone.now() - CLEANING_DELAY

        paginator = client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
        temporary_files_nb = 0
        unknown_files_nb = 0
        known_keys = set(File.objects.values_list("key", flat=True))
        self.logger.info("Checking existing files: %d files in database", len(known_keys))
        to_remove = []
        for page in page_iterator:
            obj_summaries = page.get("Contents", [])
            for obj_summary in obj_summaries:
                key = obj_summary["Key"]
                if not key.startswith(f"{TEMPORARY_STORAGE_PREFIX}/"):
                    if key not in known_keys:
                        unknown_files_nb += 1
                        if obj_summary["LastModified"] < cutoff:
                            to_remove.append(key)
                    else:
                        known_keys.remove(key)
                else:
                    temporary_files_nb += 1

        failed_deletions = 0
        if to_remove:
            self.logger.info("Found %d keys to remove from S3.", len(to_remove))
            # https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/delete_objects.html
            # > The request can contain a list of up to 1,000 keys that you want to delete.
            for batch in batched(to_remove, 1_000):
                self.logger.info("Deleting %d keys from S3.", len(batch))
                response = client.delete_objects(
                    Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                    Delete={
                        "Objects": [{"Key": key} for key in batch],
                        "Quiet": True,
                    },
                )
                if errors := response.get("Errors", []):
                    failed_deletions += len(errors)
                    self.logger.error("Failed to delete files: %s", errors)
        self.logger.info(
            "Completed bucket cleaning: found unknown=%d and temporary=%d files in the bucket, removed=%d files",
            unknown_files_nb,
            temporary_files_nb,
            len(to_remove) - failed_deletions,
        )
        if known_keys:
            # keys are present in database as File object but missing from our bucket
            self.logger.error("%d database files do not exist in the bucket: %s", len(known_keys), sorted(known_keys))

    def handle(self, *args, **options):
        self.logger.info("Starting unused file removal")
        self.delete_orphan_files()
        self.clean_s3()
