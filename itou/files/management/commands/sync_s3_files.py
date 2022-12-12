import datetime
import random

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from itou.antivirus.models import Scan
from itou.files.models import File
from itou.utils.storage.s3 import s3_client


class Command(BaseCommand):
    help = "Sync the S3 files list with the database"
    # S3 paginates with 1,000 items. Reduce the number of queries, while
    # keeping individual query size manageable.
    BATCH_SIZE = 20_000

    def handle(self, *args, **options):
        paginator = s3_client().get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=settings.S3_STORAGE_BUCKET_NAME)
        batch = []
        for page in page_iterator:
            obj_summaries = page["Contents"]
            for obj_summary in obj_summaries:
                batch.append(File(key=obj_summary["Key"], last_modified=obj_summary["LastModified"]))
            if len(batch) >= self.BATCH_SIZE:
                self.insert_or_update_files(batch)
                batch = []
        self.insert_or_update_files(batch)

    @staticmethod
    def insert_or_update_files(files):
        # S3 is used in an append-only mode, where each file name is a UUID.
        # Users cannot change a file after uploading it. It’s OK to ignore
        # conflicts, as the last_modified field does not change.
        File.objects.bulk_create(files, ignore_conflicts=True)
        now = timezone.now()
        scans = []
        seconds_in_day = 24 * 60 * 60
        for file in files:
            fake_completed_at = now.replace(hour=0, minute=0, second=0)
            fake_completed_at -= datetime.timedelta(
                days=random.randint(0, 30), seconds=random.randrange(seconds_in_day)
            )
            scans.append(Scan(file=file, clamav_completed_at=fake_completed_at))
        Scan.objects.bulk_create(scans)
