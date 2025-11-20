from datetime import timedelta

from django.template.defaultfilters import pluralize
from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.users.models import NirModificationRequest
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")

    @dry_runnable
    def handle(self, wet_run, verbosity, **options):
        qs = NirModificationRequest.objects.filter(processed_at__lt=timezone.now() - timedelta(days=182))
        count, _details = qs.delete()
        self.logger.info(f"Deleted {count} NIR modification request{pluralize(count)}")
