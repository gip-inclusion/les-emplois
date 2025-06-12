from django.conf import settings

from itou.files.models import File
from itou.utils.command import BaseCommand
from itou.utils.storage.s3 import TEMPORARY_STORAGE_PREFIX, s3_client


class Command(BaseCommand):
    help = "Sync the S3 files list with the database"
    # S3 paginates with 1,000 items. Reduce the number of queries, while
    # keeping individual query size manageable.
    BATCH_SIZE = 20_000

    def handle(self, *args, **options):
        paginator = s3_client().get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
        batch = []
        permanent_files_nb = 0
        temporary_files_nb = 0
        known_permanent_files_nb = 0
        known_keys = set(File.objects.values_list("key", flat=True))
        self.logger.info("Checking existing files: %d files in database before sync", len(known_keys))
        for page in page_iterator:
            obj_summaries = page["Contents"]
            for obj_summary in obj_summaries:
                key = obj_summary["Key"]
                if not key.startswith(f"{TEMPORARY_STORAGE_PREFIX}/"):
                    batch.append(File(key=key, last_modified=obj_summary["LastModified"]))
                    permanent_files_nb += 1
                    if key in known_keys:
                        known_permanent_files_nb += 1
                        known_keys.remove(key)
                else:
                    temporary_files_nb += 1
            if len(batch) >= self.BATCH_SIZE:
                self.insert_or_update_files(batch)
                batch = []
        self.insert_or_update_files(batch)
        self.logger.info(
            "Completed bucket sync: found permanent=%d and temporary=%d files in the bucket",
            permanent_files_nb,
            temporary_files_nb,
        )
        self.logger.info("permanent=%d files already in database before sync", known_permanent_files_nb)
        if known_keys:
            # keys are present in database as File object but missing from our bucket
            self.logger.error("%d database files do not exist in the bucket: %s", len(known_keys), sorted(known_keys))

    @staticmethod
    def insert_or_update_files(files):
        # S3 is used in an append-only mode, where each file name is a UUID.
        # Users cannot change a file after uploading it. It’s OK to ignore
        # conflicts, as the last_modified field does not change.
        File.objects.bulk_create(files, ignore_conflicts=True)
