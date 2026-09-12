import datetime

from django.db.models import Q
from django.template.defaultfilters import pluralize
from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.insertion.enums import OrientationStatus
from itou.insertion.models import Orientation
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")
        parser.add_argument("--limit", type=int, default=100)

    @dry_runnable
    def handle(self, *, wet_run, limit, **options):
        cutoff_date = timezone.now() - datetime.timedelta(Orientation.REMINDER_EMAIL_DELAY_DAYS)

        orientations = (
            Orientation.objects.filter(status=OrientationStatus.PENDING)
            .filter(
                Q(last_reminder_email_sent_at__isnull=True, created_at__lte=cutoff_date)
                | Q(last_reminder_email_sent_at__lte=cutoff_date)
            )
            .select_related(
                "service",
                "beneficiary",
                "sender",
                "sender_prescriber_organization",
                "sender_company",
            )  # used in the emails
            .order_by("created_at", "pk")[:limit]
        )

        for orientation in orientations:
            orientation.send_reminder_email()
            orientation.last_reminder_email_sent_at = timezone.now()

        counter = Orientation.objects.bulk_update(orientations, ["last_reminder_email_sent_at"])

        s = pluralize(counter)
        self.logger.info(f"Sent reminder email{s} for {counter} orientation{s}.")
