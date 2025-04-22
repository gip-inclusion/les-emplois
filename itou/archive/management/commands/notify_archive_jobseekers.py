import datetime
import logging

from django.db import transaction
from django.db.models import Exists, F, OuterRef
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.approvals.models import Approval
from itou.archive.models import ArchivedJobSeeker
from itou.eligibility.models import EligibilityDiagnosis, GEIQEligibilityDiagnosis
from itou.gps.models import FollowUpGroup
from itou.job_applications.models import JobApplication
from itou.users.models import User, UserKind
from itou.users.notifications import ArchiveJobSeeker, InactiveJobSeeker
from itou.utils.command import BaseCommand


logger = logging.getLogger(__name__)

GRACE_PERIOD = datetime.timedelta(days=30)
INACTIVITY_PERIOD = datetime.timedelta(days=365) * 2 - GRACE_PERIOD

BATCH_SIZE = 100


def inactive_jobseekers_without_related_objects(inactive_since, batch_size):
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
        .filter(
            ~Exists(job_applications),
            ~Exists(approval),
            ~Exists(eligibility_diagnosis),
            ~Exists(geiq_eligibility_diagnosis),
        )
        .job_seekers_with_last_activity()
        .filter(last_activity__lt=inactive_since)[:batch_size]
    )


def anonymized_jobseeker(user):
    kwargs = {
        "date_joined": timezone.localdate(user.date_joined).replace(day=1),
        "first_login": timezone.localdate(user.first_login).replace(day=1) if user.first_login else None,
        "last_login": timezone.localdate(user.last_login).replace(day=1) if user.last_login else None,
        "user_signup_kind": getattr(user.created_by, "kind", None),
        "department": user.department,
        "title": user.title,
        "identity_provider": user.identity_provider,
        "had_pole_emploi_id": bool(user.jobseeker_profile.pole_emploi_id),
        "had_nir": bool(user.jobseeker_profile.nir),
        "lack_of_nir_reason": user.jobseeker_profile.lack_of_nir_reason,
        "nir_sex": user.jobseeker_profile.nir[0] if user.jobseeker_profile.nir else None,
        "nir_year": user.jobseeker_profile.nir[1:3] if user.jobseeker_profile.nir else None,
        "birth_year": user.jobseeker_profile.birthdate.year if user.jobseeker_profile.birthdate else None,
    }

    return ArchivedJobSeeker(**kwargs)


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Perform the actual archiving of jobseekers",
        )

        parser.add_argument(
            "--batch-size",
            action="store",
            type=int,
            default=BATCH_SIZE,
            help="Number of jobseekers to process in a batch",
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
                InactiveJobSeeker(
                    user,
                    job_seeker=user,
                    end_of_grace_period=now + GRACE_PERIOD,
                ).send()
            User.objects.filter(id__in=[user.id for user in users]).update(upcoming_deletion_notified_at=now)

        logger.info("Notified inactive job seekers without recent activity: %s", len(users))

    def reset_notified_jobseekers_with_recent_activity(self):
        self.logger.info("Reseting inactive job seekers with recent activity")

        users_to_reset_qs = (
            User.objects.filter(kind=UserKind.JOB_SEEKER, upcoming_deletion_notified_at__isnull=False)
            .job_seekers_with_last_activity()
            .filter(last_activity__gte=F("upcoming_deletion_notified_at"))
        )

        if self.wet_run:
            reset_nb = users_to_reset_qs.update(upcoming_deletion_notified_at=None)
        else:
            reset_nb = users_to_reset_qs.count()
        self.logger.info("Reset notified job seekers with recent activity: %s", reset_nb)

    @transaction.atomic
    def archive_jobseekers_after_grace_period(self):
        now = timezone.now()
        grace_period_since = now - GRACE_PERIOD
        self.logger.info("Archiving job seekers after grace period, notified before: %s", grace_period_since)

        users_to_archive = list(
            User.objects.filter(kind=UserKind.JOB_SEEKER, upcoming_deletion_notified_at__lte=grace_period_since)[
                : self.batch_size
            ]
        )
        archived_jobseekers = [anonymized_jobseeker(user) for user in users_to_archive]

        if self.wet_run:
            for user in users_to_archive:
                ArchiveJobSeeker(
                    user,
                    job_seeker=user,
                ).send()

            ArchivedJobSeeker.objects.bulk_create(archived_jobseekers)
            self._delete_with_related_objects(users_to_archive)

        self.logger.info("Archived jobseekers after grace period, count: %d", len(archived_jobseekers))

    def _delete_with_related_objects(self, users):
        FollowUpGroup.objects.filter(beneficiary__in=users).delete()
        User.objects.filter(id__in=[user.id for user in users]).delete()

    @monitor(
        monitor_slug="notify_archive_jobseekers",
        monitor_config={
            "schedule": {"type": "crontab", "value": "*/5 7-20 * * MON-FRI"},
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
        self.logger.info("Start notifying and archiving jobseekers in %s mode", "wet_run" if wet_run else "dry_run")

        self.reset_notified_jobseekers_with_recent_activity()
        self.notify_inactive_jobseekers()
        self.archive_jobseekers_after_grace_period()
