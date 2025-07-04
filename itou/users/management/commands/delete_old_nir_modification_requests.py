from datetime import timedelta

from django.db import transaction
from django.template.defaultfilters import pluralize
from django.utils import timezone

from itou.users.models import NirModificationRequest
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")

    @transaction.atomic()
    def handle(self, wet_run, verbosity, **options):
        qs = NirModificationRequest.objects.filter(processed_at__lt=timezone.now() - timedelta(days=182))
        if wet_run:
            prefix = "Deleted"
            count, _details = qs.delete()
        else:
            prefix = "Would delete"
            count = qs.count()
        self.logger.info(f"{prefix} {count} NIR modification request{pluralize(count)}")
