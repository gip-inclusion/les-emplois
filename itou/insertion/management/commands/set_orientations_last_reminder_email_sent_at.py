from datetime import timedelta

from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.insertion.enums import OrientationStatus
from itou.insertion.models import Orientation
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    help = """
    DORA sends reminder emails at day 10 and day 20 for PENDING orientations.
    To avoid sending emails from here that have already been sent by DORA, we
    set `last_reminder_email_sent_at` value, which is deterministic.
    https://github.com/gip-inclusion/dora/blob/main/back/dora/orientations/management/commands/send_orientations_reminders.py
    """

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")
        parser.add_argument("--limit", type=int, default=100)

    @dry_runnable
    def handle(self, *, wet_run, limit, **options):
        reminder_one_cutoff = timezone.now() - timedelta(days=Orientation.REMINDER_EMAIL_DELAY_DAYS)
        reminder_two_cutoff = timezone.now() - timedelta(days=Orientation.REMINDER_EMAIL_DELAY_DAYS * 2)
        reminder_one_orientations = Orientation.objects.filter(
            status=OrientationStatus.PENDING, created_at__range=(reminder_two_cutoff, reminder_one_cutoff)
        )
        reminder_two_orientations = Orientation.objects.filter(
            status=OrientationStatus.PENDING, created_at__lt=reminder_two_cutoff
        )

        for orientation in reminder_one_orientations:
            orientation.last_reminder_email_sent_at = orientation.created_at + timedelta(
                days=Orientation.REMINDER_EMAIL_DELAY_DAYS
            )
        for orientation in reminder_two_orientations:
            orientation.last_reminder_email_sent_at = orientation.created_at + timedelta(
                days=Orientation.REMINDER_EMAIL_DELAY_DAYS * 2
            )

        Orientation.objects.bulk_update(
            list(reminder_one_orientations) + list(reminder_two_orientations), ["last_reminder_email_sent_at"]
        )

        self.logger.info(f"Updated {len(reminder_one_orientations)} orientations between 10 and 20 days old.")
        self.logger.info(f"Updated {len(reminder_two_orientations)} orientations older than 20 days old.")
