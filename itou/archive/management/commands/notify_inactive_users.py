import logging

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.approvals.models import Approval
from itou.eligibility.models import EligibilityDiagnosis, GEIQEligibilityDiagnosis
from itou.users.models import User, UserKind
from itou.users.notifications import InactiveUser
from itou.utils.command import BaseCommand
from itou.utils.constants import GRACE_PERIOD, INACTIVITY_PERIOD


logger = logging.getLogger(__name__)

BATCH_SIZE = 200


def inactive_jobseekers_without_related_objects(inactive_since, batch_size):
    approval = Approval.objects.filter(user_id=OuterRef("pk"))
    eligibility_diagnosis = EligibilityDiagnosis.objects.filter(
        job_seeker=OuterRef("pk"),
    )
    geiq_eligibility_diagnosis = GEIQEligibilityDiagnosis.objects.filter(
        job_seeker=OuterRef("pk"),
    )

    return (
        User.objects.filter(
            kind=UserKind.JOB_SEEKER,
            upcoming_deletion_notified_at__isnull=True,
        )
        .filter(
            ~Exists(approval),
            ~Exists(eligibility_diagnosis),
            ~Exists(geiq_eligibility_diagnosis),
        )
        .job_seekers_with_last_activity()
        .filter(last_activity__lt=inactive_since)[:batch_size]
    )


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Perform the actual archiving of users",
        )

        parser.add_argument(
            "--batch-size",
            action="store",
            type=int,
            default=BATCH_SIZE,
            help="Number of users to process in a batch",
        )

    @transaction.atomic
    def notify_inactive_jobseekers(self):
        now = timezone.now()
        inactive_since = now - INACTIVITY_PERIOD
        self.logger.info("Notifying inactive job seekers without activity before: %s", inactive_since)
        users = list(
            inactive_jobseekers_without_related_objects(inactive_since=inactive_since, batch_size=self.batch_size)
        )

        if self.wet_run:
            for user in users:
                InactiveUser(
                    user,
                    end_of_grace_period=now + GRACE_PERIOD,
                ).send()
            User.objects.filter(id__in=[user.id for user in users]).update(upcoming_deletion_notified_at=now)

        logger.info("Notified inactive job seekers without recent activity: %s", len(users))

    @monitor(
        monitor_slug="notify_inactive_users",
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
        self.logger.info("Start notifying inactive users in %s mode", "wet_run" if wet_run else "dry_run")

        self.notify_inactive_jobseekers()
