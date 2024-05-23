from datetime import timedelta

from django.db import transaction
from django.template.defaultfilters import pluralize
from django.utils import timezone

from itou.emails.models import Email
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @transaction.atomic
    def handle(self, *, wet_run, **options):
        qs = Email.objects.filter(created_at__lt=timezone.now() - timedelta(days=365))
        if wet_run:
            prefix = "Deleted"
            count, _details = qs.delete()
        else:
            prefix = "Would delete"
            count = qs.count()
        self.stdout.write(f"{prefix} {count} email{pluralize(count)}.")
