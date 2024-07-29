import datetime

from django.template.defaultfilters import pluralize
from django.utils import timezone

from itou.job_applications.enums import ARCHIVABLE_JOB_APPLICATION_STATES
from itou.job_applications.models import JobApplication
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def handle(self, **options):
        now = timezone.now()
        count = JobApplication.objects.filter(
            archived_at=None,
            state__in=ARCHIVABLE_JOB_APPLICATION_STATES,
            updated_at__lte=now - datetime.timedelta(days=180),
        ).update(archived_at=now)
        s = pluralize(count)
        self.stdout.write(f"Archived {count} job application{s}.")
