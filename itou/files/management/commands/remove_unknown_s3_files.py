import datetime

from django.conf import settings
from django.utils import timezone

from itou.files.models import File
from itou.utils.command import BaseCommand
from itou.utils.storage.s3 import TEMPORARY_STORAGE_PREFIX, s3_client


# Wait a bit before deleting a unknown file from S3 in case the database File is still not commited
S3_CLEANING_DELAY = datetime.timedelta(days=1)


class Command(BaseCommand):
    help = "Remove any S3 files not listed in the database"

    def handle(self, *args, **options):
        client = s3_client()
        cutoff = timezone.now() - S3_CLEANING_DELAY

        paginator = client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
        temporary_files_nb = 0
        unknown_files_nb = 0
        removed_files_nb = 0
        known_keys = set(File.objects.values_list("key", flat=True))
        self.logger.info("Checking existing files: %d files in database", len(known_keys))
        for page in page_iterator:
            obj_summaries = page["Contents"]
            for obj_summary in obj_summaries:
                key = obj_summary["Key"]
                if not key.startswith(f"{TEMPORARY_STORAGE_PREFIX}/"):
                    if key not in known_keys:
                        unknown_files_nb += 1
                        if obj_summary["LastModified"] < cutoff:
                            removed_files_nb += 1
                            client.delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
                    else:
                        known_keys.remove(key)
                else:
                    temporary_files_nb += 1
        self.logger.info(
            "Completed bucket cleaning: found unknown=%d and temporary=%d files in the bucket, removed=%d files",
            unknown_files_nb,
            temporary_files_nb,
            removed_files_nb,
        )
        if known_keys:
            # keys are present in database as File object but missing from our bucket
            self.logger.error("%d database files do not exist in the bucket: %s", len(known_keys), sorted(known_keys))
