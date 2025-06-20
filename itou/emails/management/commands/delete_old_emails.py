from datetime import timedelta

from django.template.defaultfilters import pluralize
from django.utils import timezone

from itou.emails.models import Email
from itou.utils.command import BaseCommand, dry_runnable


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @dry_runnable
    def handle(self, **options):
        qs = Email.objects.filter(created_at__lt=timezone.now() - timedelta(days=62))
        count, _details = qs.delete()
        self.logger.info(f"Deleted {count} email{pluralize(count)}")
