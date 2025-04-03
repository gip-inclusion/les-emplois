import datetime
import logging

from django.db import transaction
from django.db.models import Exists, F, OuterRef
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.approvals.models import Approval
from itou.users.models import User, UserKind
from itou.users.notifications import DeactivateJobSeeker, InactiveJobSeeker
from itou.utils.command import BaseCommand


logger = logging.getLogger(__name__)

INACTIVE_SINCE = timezone.now() - datetime.timedelta(days=365)
GRACE_PERIOD = datetime.timedelta(days=30)
NOW = timezone.now()
BATCH_SIZE = 50


def standalone_jobseekers():
    from itou.eligibility.models import EligibilityDiagnosis, GEIQEligibilityDiagnosis
    from itou.gps.models import FollowUpGroup
    from itou.job_applications.models import JobApplication

    job_applications = JobApplication.objects.filter(job_seeker=OuterRef("pk"))
    approval = Approval.objects.filter(user_id=OuterRef("pk"))
    eligibility_diagnosis = EligibilityDiagnosis.objects.filter(
        job_seeker=OuterRef("pk"),
    )
    geiq_eligibility_diagnosis = GEIQEligibilityDiagnosis.objects.filter(
        job_seeker=OuterRef("pk"),
    )
    follow_up_group = FollowUpGroup.objects.filter(
        beneficiary=OuterRef("pk"),
    )

    return User.objects.filter(
        kind=UserKind.JOB_SEEKER,
        upcoming_deletion_notified_at__isnull=True,
        is_active=True,
    ).filter(
        ~Exists(job_applications),
        ~Exists(approval),
        ~Exists(eligibility_diagnosis),
        ~Exists(geiq_eligibility_diagnosis),
        ~Exists(follow_up_group),
    )


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Send upcoming deletion emails to inactive job seekers",
        )

        parser.add_argument(
            "--batch-size",
            action="store",
            type=int,
            default=BATCH_SIZE,
            help="batch size to process",
        )

    @transaction.atomic
    def notify_inactive_jobseekers(self):
        users_to_update = []
        self.logger.info("Notifying inactive job seekers without activity before: %s", INACTIVE_SINCE)

        users = (
            standalone_jobseekers()
            .job_seekers_with_last_activity()
            .filter(last_activity__lt=INACTIVE_SINCE)[: self.batch_size]
        )

        for user in users:
            if self.wet_run:
                user.upcoming_deletion_notified_at = NOW
                InactiveJobSeeker(
                    user,
                    job_seeker=user,
                    end_of_grace_period=NOW + GRACE_PERIOD,
                ).send()
                users_to_update.append(user)

        User.objects.bulk_update(users_to_update, ["upcoming_deletion_notified_at"])
        logger.info("Notified inactive job seekers without recent activity: %s", len(users))

    @transaction.atomic
    def reset_notified_jobseekers_with_recent_activity(self):
        users_to_update = []
        self.logger.info("Reseting inactive job seekers with recent activity")

        for user in list(
            users := User.objects.filter(
                kind=UserKind.JOB_SEEKER, upcoming_deletion_notified_at__isnull=False, is_active=True
            )
            .job_seekers_with_last_activity()
            .filter(
                last_activity__gte=F("upcoming_deletion_notified_at"),
            )
        )[: self.batch_size]:
            if self.wet_run:
                user.upcoming_deletion_notified_at = None
                users_to_update.append(user)

        User.objects.bulk_update(users_to_update, ["upcoming_deletion_notified_at"])
        self.logger.info("Reset notified job seekers with recent activity: %s", len(users))

    @transaction.atomic
    def deactivate_jobseekers_after_grace_period(self):
        extended_grace_period = NOW - GRACE_PERIOD - datetime.timedelta(days=2)
        users_to_update = []
        self.logger.info("Deactivating job seekers after grace period, notified before: %s", extended_grace_period)

        for user in list(
            users := User.objects.filter(
                kind=UserKind.JOB_SEEKER, upcoming_deletion_notified_at__lte=extended_grace_period, is_active=True
            )
        )[: self.batch_size]:
            if self.wet_run:
                DeactivateJobSeeker(
                    user,
                    job_seeker=user,
                ).send()
                user.is_active = False
                users_to_update.append(user)

        User.objects.bulk_update(users_to_update, ["is_active"])
        self.logger.info("Deactivated job seekers after grace period: %s", len(users))

    @monitor(monitor_slug="notify-deactivate-inactive-jobseekers")
    def handle(self, *args, wet_run, batch_size, **options):
        self.wet_run = wet_run
        self.batch_size = batch_size

        self.logger.info(
            "Starting notify deactivate inactive jobseekers command, %s mode", "wet_run" if self.wet_run else "dry_run"
        )

        self.notify_inactive_jobseekers()
        self.reset_notified_jobseekers_with_recent_activity()
        self.deactivate_jobseekers_after_grace_period()

        self.logger.info("Finished notify deactivate inactive jobseekers command")
