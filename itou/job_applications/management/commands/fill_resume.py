import logging

from django.conf import settings
from django.core.files.storage import default_storage, storages

from itou.files.models import File
from itou.job_applications.models import JobApplication
from itou.utils.command import BaseCommand


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--batch-size",
            action="store",
            type=int,
            default=10_000,
            help="Number of job application to process",
            dest="batch_size",
        )

    def get_key_from_link(self, link):
        separator = f"{settings.AWS_STORAGE_BUCKET_NAME}/"
        if default_storage.location:
            separator += f"{default_storage.location}/"
        return link.split(separator)[1]

    def handle(self, batch_size, **options):
        # Just in case we have some bad link, filter on settings.AWS_STORAGE_BUCKET_NAME
        job_apps = list(
            JobApplication.objects.exclude(resume_link="")
            .filter(resume_link__icontains=settings.AWS_STORAGE_BUCKET_NAME, resume=None)
            .order_by("resume_link", "created_at")[:batch_size]
        )

        public_storage = storages["public"]
        keys = [self.get_key_from_link(job_app.resume_link) for job_app in job_apps]
        files = {file.key: file for file in File.objects.filter(key__in=keys)}
        previous_key = None

        # Check first job_app : maybe the last job_app of the previous batch had the same key
        if JobApplication.objects.filter(resume__key=keys[0]).exists():
            previous_key = keys[0]

        for job_app in job_apps:
            key = self.get_key_from_link(job_app.resume_link)
            if previous_key == key:
                # Same key as previous file : we need to create a new one
                new_file = files[key].copy()
                job_app.resume = new_file
                job_app.resume_link = public_storage.url(new_file.key)
            elif key in files:
                job_app.resume = files[key]
            previous_key = key

        JobApplication.objects.bulk_update(job_apps, ["resume_link", "resume"])

        logger.info("Filled %s job aplications resume", len(job_apps))
