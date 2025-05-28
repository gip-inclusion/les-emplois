import datetime
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Exists, F, Max, OuterRef, Q, Subquery
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.approvals.models import Approval
from itou.archive.models import ArchivedApplication, ArchivedJobSeeker
from itou.companies.enums import CompanyKind
from itou.companies.models import JobDescription
from itou.eligibility.models import EligibilityDiagnosis, GEIQEligibilityDiagnosis
from itou.gps.models import FollowUpGroup
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication, JobApplicationTransitionLog
from itou.users.models import User, UserKind
from itou.users.notifications import ArchiveUser, InactiveUser
from itou.utils.command import BaseCommand
from itou.utils.constants import GRACE_PERIOD, INACTIVITY_PERIOD


logger = logging.getLogger(__name__)

BATCH_SIZE = 100


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


def get_year_month_or_none(date=None):
    if not date:
        return None

    if isinstance(date, datetime.datetime):
        return timezone.localdate(date).replace(day=1)

    return date.replace(day=1)


def anonymized_jobseeker(user):
    return ArchivedJobSeeker(
        date_joined=get_year_month_or_none(user.date_joined),
        first_login=get_year_month_or_none(user.first_login),
        last_login=get_year_month_or_none(user.last_login),
        user_signup_kind=getattr(user.created_by, "kind", None),
        department=user.department,
        title=user.title,
        identity_provider=user.identity_provider,
        had_pole_emploi_id=bool(user.jobseeker_profile.pole_emploi_id),
        had_nir=bool(user.jobseeker_profile.nir),
        lack_of_nir_reason=user.jobseeker_profile.lack_of_nir_reason,
        nir_sex=user.jobseeker_profile.nir[0] if user.jobseeker_profile.nir else None,
        nir_year=user.jobseeker_profile.nir[1:3] if user.jobseeker_profile.nir else None,
        birth_year=user.jobseeker_profile.birthdate.year if user.jobseeker_profile.birthdate else None,
        count_accepted_applications=user.count_accepted_applications,
        count_IAE_applications=user.count_IAE_applications,
        count_total_applications=user.count_total_applications,
    )


def anonymized_jobapplication(obj):
    return ArchivedApplication(
        job_seeker_birth_year=(
            obj.job_seeker.jobseeker_profile.birthdate.year if obj.job_seeker.jobseeker_profile.birthdate else None
        ),
        job_seeker_department_same_as_company_department=obj.job_seeker.department == obj.to_company.department,
        sender_kind=obj.sender.kind,
        sender_company_kind=obj.sender_company.kind if obj.sender_company else None,
        sender_prescriber_organization_kind=(
            obj.sender_prescriber_organization.kind if obj.sender_prescriber_organization else None
        ),
        sender_prescriber_organization_authorization_status=(
            obj.sender_prescriber_organization.authorization_status if obj.sender_prescriber_organization else None
        ),
        company_kind=obj.to_company.kind,
        company_department=obj.to_company.department,
        company_naf=obj.to_company.naf,
        company_has_convention=obj.to_company.convention is not None,
        applied_at=get_year_month_or_none(obj.created_at),
        processed_at=get_year_month_or_none(obj.processed_at),
        last_transition_at=(
            get_year_month_or_none(obj.last_transition_at)
            if obj.last_transition_at
            else get_year_month_or_none(obj.created_at)
        ),
        had_resume=bool(obj.resume_id),
        origin=obj.origin,
        state=obj.state,
        refusal_reason=obj.refusal_reason,
        has_been_transferred=obj.transferred_at is not None,
        number_of_jobs_applied_for=obj.number_of_jobs_applied_for or 0,
        has_diagoriente_invitation=obj.diagoriente_invite_sent_at is not None,
        hiring_rome=obj.hired_job.appellation.rome if obj.hired_job else None,
        hiring_contract_type=obj.hired_job.contract_type if obj.hired_job else None,
        hiring_contract_nature=obj.hired_job.contract_nature if obj.hired_job else None,
        hiring_start_date=get_year_month_or_none(obj.hiring_start_at),
        hiring_without_approval=obj.hiring_without_approval,
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

        # jobseekers
        users_to_archive = list(
            User.objects.filter(
                kind=UserKind.JOB_SEEKER, upcoming_deletion_notified_at__lte=grace_period_since
            ).annotate(
                count_accepted_applications=Count(
                    "job_applications__id", filter=Q(job_applications__state=JobApplicationState.ACCEPTED)
                ),
                count_IAE_applications=Count(
                    "job_applications__id", filter=Q(job_applications__to_company__kind__in=CompanyKind.siae_kinds())
                ),
                count_total_applications=Count("job_applications__id"),
            )[: self.batch_size]
        )

        archived_jobseekers = [anonymized_jobseeker(user) for user in users_to_archive]

        # job applications
        number_of_jobs_applied_for_subquery = (
            JobDescription.objects.filter(jobapplication__id=OuterRef("id"))
            .values("jobapplication")
            .annotate(number_of_jobs_applied_for=Count("pk"))
            .values("number_of_jobs_applied_for")
        )
        last_transition_at_subquery = (
            JobApplicationTransitionLog.objects.filter(job_application__id=OuterRef("id"))
            .values("job_application")
            .annotate(last_transition_at=Max("timestamp"))
            .values("last_transition_at")
        )
        jobapplications_to_archive = (
            JobApplication.objects.filter(job_seeker__in=users_to_archive)
            .annotate(
                number_of_jobs_applied_for=Subquery(number_of_jobs_applied_for_subquery),
                last_transition_at=Subquery(last_transition_at_subquery),
            )
            .select_related(
                "job_seeker",
                "sender",
                "sender_company",
                "sender_prescriber_organization",
                "to_company",
                "hired_job",
                "hired_job__appellation",
            )
        )
        archived_jobapplications = [
            anonymized_jobapplication(job_application) for job_application in jobapplications_to_archive
        ]

        if self.wet_run:
            for user in users_to_archive:
                ArchiveUser(
                    user,
                ).send()

            ArchivedJobSeeker.objects.bulk_create(archived_jobseekers)
            ArchivedApplication.objects.bulk_create(archived_jobapplications)
            self._delete_jobseekers_with_related_objects(users_to_archive)

        self.logger.info("Archived jobseekers after grace period, count: %d", len(archived_jobseekers))
        self.logger.info("Archived job applications after grace period, count: %d", len(archived_jobapplications))

    def _delete_jobseekers_with_related_objects(self, users):
        FollowUpGroup.objects.filter(beneficiary__in=users).delete()
        JobApplication.objects.filter(job_seeker__in=users).delete()
        User.objects.filter(id__in=[user.id for user in users]).delete()

    @monitor(
        monitor_slug="notify_archive_users",
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
        if settings.SUSPEND_NOTIFY_ARCHIVE_USERS:
            self.logger.info("Archiving users is suspended, exiting command")
            return

        self.wet_run = wet_run
        self.batch_size = batch_size
        self.logger.info("Start notifying and archiving users in %s mode", "wet_run" if wet_run else "dry_run")

        self.reset_notified_jobseekers_with_recent_activity()
        self.notify_inactive_jobseekers()
        self.archive_jobseekers_after_grace_period()
