import datetime
import logging

from django.db import transaction
from django.db.models import Exists, OuterRef
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
    from itou.job_applications.models import JobApplication

    job_applications = JobApplication.objects.filter(job_seeker=OuterRef("pk"))
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
        .annotate(
            job_applications_exists=Exists(job_applications),
            approval_exists=Exists(approval),
            diag_exists=Exists(eligibility_diagnosis),
            geiq_diag_exists=Exists(geiq_eligibility_diagnosis),
        )
        .filter(
            job_applications_exists=False,
            approval_exists=False,
            diag_exists=False,
            geiq_diag_exists=False,
        )
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
            "--size",
            action="store_true",
            help="batch size to process",
        )

    @transaction.atomic
    def notify_inactive_jobseekers(self):
        self.logger.info("Notifying inactive job seekers without activity before: %s", INACTIVE_SINCE)
        for user in (
            users := standalone_jobseekers()
            .exclude(upcoming_deletion_notified_at__isnull=False)
            .job_seekers_with_last_activity()
            .filter(last_activity__lt=INACTIVE_SINCE)[: self.batch_size]
        ):
            # order_by('last_activity') seems to be costly operation ^^
            user.upcoming_deletion_notified_at = NOW
            if self.wet_run:
                InactiveJobSeeker(
                    user,
                    job_seeker=user,
                    end_of_grace_period=NOW + GRACE_PERIOD,
                ).send()

        if self.wet_run:
            User.objects.bulk_update(users, ["upcoming_deletion_notified_at"])
        logger.info("Notified inactive job seekers without recent activity: %s", len(users))

    @transaction.atomic
    def reset_notified_jobseekers_with_recent_activity(self):
        users = (
            User.objects.filter(kind=UserKind.JOB_SEEKER, upcoming_deletion_notified_at__isnull=False)
            .job_seekers_with_last_activity()
            .filter(
                last_activity__gt=INACTIVE_SINCE,
            )
        )

        if self.wet_run:
            users.update(
                upcoming_deletion_notified_at=None,
            )
        self.logger.info("Reset notified job seekers with recent activity: %s", len(users))

    @transaction.atomic
    def deactivate_jobseekers_after_grace_period(self):
        extended_grace_period = NOW - GRACE_PERIOD - datetime.timedelta(days=2)
        self.logger.info("Deactivating job seekers after grace period, notified before: %s", extended_grace_period)
        for user in (
            users := User.objects.filter(upcoming_deletion_notified_at__lt=extended_grace_period)[: self.batch_size]
        ):
            user.is_active = False
            if self.wet_run:
                DeactivateJobSeeker(
                    user,
                    job_seeker=user,
                ).send()

        if self.wet_run:
            User.objects.bulk_update(users, ["is_active"])

        self.logger.info("Deactivated job seekers after grace period: %s", len(users))

    @monitor(monitor_slug="notify-deactivate-inactive-jobseekers")
    def handle(self, *args, **options):
        self.wet_run = options["wet_run"]
        self.batch_size = options["size"] if options["size"] else BATCH_SIZE

        self.logger.info(
            "Starting notify deactivate inactive jobseekers command, %s mode", "wet_run" if self.wet_run else "dry_run"
        )

        self.notify_inactive_jobseekers()
        self.reset_notified_jobseekers_with_recent_activity()
        self.deactivate_jobseekers_after_grace_period()

        self.logger.info("Finished notify deactivate inactive jobseekers command")
