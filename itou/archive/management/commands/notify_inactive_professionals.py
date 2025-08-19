from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.archive.constants import GRACE_PERIOD, INACTIVITY_PERIOD
from itou.users.models import User, UserKind
from itou.users.notifications import InactiveUser
from itou.utils.command import BaseCommand


BATCH_SIZE = 200


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Perform the notification of inactive professionals",
        )

        parser.add_argument(
            "--batch-size",
            action="store",
            type=int,
            default=BATCH_SIZE,
            help="Number of professionals to process in a batch",
        )

    def notify_inactive_professionals(self):
        now = timezone.now()
        inactive_since = now - INACTIVITY_PERIOD
        self.logger.info("Notifying inactive professionals without activity before: %s", inactive_since)

        users = list(
            User.objects.filter(
                kind__in=UserKind.professionals(),
                upcoming_deletion_notified_at__isnull=True,
                last_login__lt=inactive_since,
            )[: self.batch_size]
        )

        if self.wet_run:
            for user in users:
                InactiveUser(user, end_of_grace_period=now + GRACE_PERIOD, inactivity_since=inactive_since).send()
            User.objects.filter(id__in=[user.id for user in users]).update(upcoming_deletion_notified_at=now)

        self.logger.info("Notified inactive professionals without recent activity: %s", len(users))

    @monitor(
        monitor_slug="notify_inactive_professionals",
        monitor_config={
            "schedule": {"type": "crontab", "value": "0 7,10,13 * * MON-FRI"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 2,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    def handle(self, *args, wet_run, batch_size, **options):
        self.wet_run = wet_run
        self.batch_size = batch_size
        self.logger.info("Start notifying inactive professionals in %s mode", "wet_run" if wet_run else "dry_run")

        self.notify_inactive_professionals()
