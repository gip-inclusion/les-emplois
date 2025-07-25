from django.db.models import Exists, OuterRef
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.approvals.models import Approval
from itou.eligibility.models import EligibilityDiagnosis, GEIQEligibilityDiagnosis
from itou.users.models import User, UserKind
from itou.users.notifications import InactiveUser
from itou.utils.command import BaseCommand
from itou.utils.constants import GRACE_PERIOD, INACTIVITY_PERIOD


BATCH_SIZE = 200


def inactive_jobseekers_without_recent_related_objects(inactive_since, batch_size):
    recent_approval = Approval.objects.filter(user_id=OuterRef("pk"), end_at__gt=inactive_since)
    recent_eligibility_diagnosis = EligibilityDiagnosis.objects.filter(
        job_seeker=OuterRef("pk"), expires_at__gt=inactive_since
    )
    recent_geiq_eligibility_diagnosis = GEIQEligibilityDiagnosis.objects.filter(
        job_seeker=OuterRef("pk"), expires_at__gt=inactive_since
    )

    return (
        User.objects.filter(
            kind=UserKind.JOB_SEEKER,
            upcoming_deletion_notified_at__isnull=True,
        )
        .filter(
            ~Exists(recent_approval),
            ~Exists(recent_eligibility_diagnosis),
            ~Exists(recent_geiq_eligibility_diagnosis),
        )
        .job_seekers_with_last_activity()
        .filter(last_activity__lt=inactive_since)[:batch_size]
    )


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
                inactive_since=inactive_since, batch_size=self.batch_size
            )
        )

        if self.wet_run:
            for user in users:
                InactiveUser(
                    user,
                    end_of_grace_period=now + GRACE_PERIOD,
                ).send()
            User.objects.filter(id__in=[user.id for user in users]).update(upcoming_deletion_notified_at=now)

        self.logger.info("Notified inactive job seekers without recent activity: %s", len(users))

    @monitor(
        monitor_slug="notify_inactive_jobseekers",
        monitor_config={
            "schedule": {"type": "crontab", "value": "0 7 * * MON-FRI"},
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
