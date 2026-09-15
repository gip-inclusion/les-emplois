from django.conf import settings
from django.core.files import File
from itoutils.django.commands import dry_runnable

from itou.files.models import save_file
from itou.insertion.enums import OrientationStatus
from itou.insertion.models import Orientation
from itou.utils.command import BaseCommand
from itou.utils.storage.s3 import dora_s3_client


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @dry_runnable
    def handle(self, *, wet_run, **options):
        orientations_with_attachments = (
            Orientation.objects.exclude(attachments=[])
            .exclude(status__in=[OrientationStatus.REJECTED, OrientationStatus.EXPIRED])
            .filter(documents__isnull=True)
        )
        for orientation in orientations_with_attachments:
            emplois_attachments = []
            for dora_attachment in orientation.attachments:
                try:
                    dora_file = File(
                        dora_s3_client().get_object(
                            Bucket=settings.DORA_AWS_S3_STORAGE_BUCKET_NAME, Key=dora_attachment
                        )["Body"],
                        name=dora_attachment.split("/")[-1],
                    )
                except dora_s3_client().exceptions.NoSuchKey:
                    self.logger.info(f"Attachments for orientation={orientation.pk} were not found.")
                    continue
                if wet_run:
                    saved_file = save_file(folder="orientations/", file=dora_file, anonymize_filename=False)
                    emplois_attachments.append(saved_file)
            orientation.documents.set(emplois_attachments)
            self.logger.info(f"Added {len(orientation.attachments)} documents to orientation={orientation.pk}.")
