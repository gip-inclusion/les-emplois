from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.archive.utils import inactive_jobseekers_without_recent_related_objects
from itou.users.models import User
from itou.users.notifications import InactiveUser
from itou.utils.command import BaseCommand
from itou.utils.constants import GRACE_PERIOD, INACTIVITY_PERIOD


BATCH_SIZE = 200


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Perform the notification of inactive job seekers",
        )

        parser.add_argument(
            "--batch-size",
            action="store",
            type=int,
            default=BATCH_SIZE,
            help="Number of job seekers to process in a batch",
        )

    def notify_inactive_jobseekers(self):
        now = timezone.now()
        inactive_since = now - INACTIVITY_PERIOD
        self.logger.info("Notifying inactive job seekers without recent related objects before: %s", inactive_since)
        users = list(
            inactive_jobseekers_without_recent_related_objects(
                inactive_since=inactive_since, notified=False, batch_size=self.batch_size
            )
        )

        if self.wet_run:
            for user in users:
                InactiveUser(user, end_of_grace_period=now + GRACE_PERIOD, inactivity_since=inactive_since).send()
            User.objects.filter(id__in=[user.id for user in users]).update(upcoming_deletion_notified_at=now)

        self.logger.info("Notified inactive job seekers without recent activity: %s", len(users))

    @monitor(
        monitor_slug="notify_inactive_jobseekers",
        monitor_config={
            "schedule": {"type": "crontab", "value": "*/30 7-18 * * MON-FRI"},
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
        self.logger.info("Start notifying inactive job seekers in %s mode", "wet_run" if wet_run else "dry_run")

        self.notify_inactive_jobseekers()
