from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.archive.constants import GRACE_PERIOD, INACTIVITY_PERIOD
from itou.archive.utils import inactive_jobseekers_without_recent_related_objects
from itou.users.models import User
from itou.users.notifications import InactiveUser
from itou.utils.command import BaseCommand, dry_runnable


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

    def notify_inactive_jobseekers(self, batch_size):
        now = timezone.now()
        inactive_since = now - INACTIVITY_PERIOD
        self.logger.info("Notifying inactive job seekers without recent related objects before: %s", inactive_since)
        users = list(
            inactive_jobseekers_without_recent_related_objects(
                inactive_since=inactive_since, notified=False, batch_size=batch_size
            )
        )

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
    @dry_runnable
    def handle(self, *args, batch_size, **options):
        self.notify_inactive_jobseekers(batch_size=batch_size)
