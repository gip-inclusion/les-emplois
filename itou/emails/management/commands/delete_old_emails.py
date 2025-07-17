from datetime import timedelta

from django.template.defaultfilters import pluralize
from django.utils import timezone

from itou.emails.models import Email
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def handle(self, *, wet_run, **options):
        qs = Email.objects.filter(created_at__lt=timezone.now() - timedelta(days=62))
        if wet_run:
            prefix = "Deleted"
            count, _details = qs.delete()
        else:
            prefix = "Would delete"
            count = qs.count()
        self.logger.info(f"{prefix} {count} email{pluralize(count)}")
