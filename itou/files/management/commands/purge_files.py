import datetime

from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.utils import timezone

from itou.files.models import File
from itou.utils.command import BaseCommand


BATCH_SIZE = 1_000


class Command(BaseCommand):
    def handle(self, *args, **options):
        deleted = 0
        for file in File.objects.filter(deleted_at__lte=timezone.now() - datetime.timedelta(days=1))[:BATCH_SIZE]:
            try:
                with transaction.atomic():
                    s3_key = file.key
                    # Try to delete file from DB first : if we cannot, don't remove from s3
                    file.delete()
                    # If we could remove it, remove from S3
                    default_storage.delete(s3_key)
                    deleted += 1
            except IntegrityError:
                self.logger.exception(f"Could not delete protected file {file.key}")
            except Exception:
                self.logger.exception(f"Could not remove {file.key} from S3")

        self.logger.info(f"Purged {deleted} files")
