import logging

from django.conf import settings
from django.db.models import F
from sentry_sdk.crons import monitor

from itou.users.models import User, UserKind
from itou.utils.command import BaseCommand


logger = logging.getLogger(__name__)

BATCH_SIZE = 100


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Perform the anonymization of professionals",
        )

        parser.add_argument(
            "--batch-size",
            action="store",
            type=int,
            default=BATCH_SIZE,
            help="Number of users to process in a batch",
        )

    def reset_notified_professionals_with_recent_activity(self):
        self.logger.info("Reseting inactive professionals with recent activity")

        users_to_reset_qs = User.objects.filter(
            kind__in=UserKind.professionals(),
            upcoming_deletion_notified_at__isnull=False,
            last_login__gte=F("upcoming_deletion_notified_at"),
        )

        if self.wet_run:
            reset_nb = users_to_reset_qs.update(upcoming_deletion_notified_at=None)
        else:
            reset_nb = users_to_reset_qs.count()
        self.logger.info("Reset notified professionals with recent activity: %s", reset_nb)

    @monitor(
        monitor_slug="notify_archive_users",
        monitor_config={
            "schedule": {"type": "crontab", "value": "0 7-20 * * MON-FRI"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 2,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    def handle(self, *args, wet_run, batch_size, **options):
        if settings.SUSPEND_ANONYMIZE_PROFESSIONALS:
            self.logger.info("Anonymizing professionals is suspended, exiting command")
            return
        self.wet_run = wet_run
        self.batch_size = batch_size
        self.logger.info("Start anonymizing professionals in %s mode", "wet_run" if wet_run else "dry_run")

        self.reset_notified_professionals_with_recent_activity()
