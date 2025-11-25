from django.conf import settings
from django.contrib.postgres.aggregates import ArrayAgg
from django.db import transaction
from django.db.models import Count, F, Max, Min, OuterRef, Q, Subquery, Sum
from django.utils import timezone
from itoutils.django.commands import dry_runnable
from sentry_sdk.crons import monitor

from itou.approvals.models import Approval, Prolongation, Suspension
from itou.archive.constants import GRACE_PERIOD, INACTIVITY_PERIOD
from itou.archive.models import (
    AnonymizedApplication,
    AnonymizedApproval,
    AnonymizedGEIQEligibilityDiagnosis,
    AnonymizedJobSeeker,
    AnonymizedSIAEEligibilityDiagnosis,
)
from itou.archive.tasks import async_delete_contact
from itou.archive.utils import (
    count_related_subquery,
    get_year_month_or_none,
    inactive_jobseekers_without_recent_related_objects,
)
from itou.companies.enums import CompanyKind
from itou.companies.models import JobDescription
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.employee_record.models import EmployeeRecord
from itou.files.models import File
from itou.gps.models import FollowUpGroup
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication, JobApplicationTransitionLog
from itou.users.models import User, UserKind
from itou.users.notifications import ArchiveUser
from itou.utils.command import BaseCommand


BATCH_SIZE = 200


def anonymized_jobseeker(user):
    return AnonymizedJobSeeker(
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
        count_approvals=user.count_approvals,
        first_approval_start_at=get_year_month_or_none(user.first_approval_start_at),
        last_approval_end_at=get_year_month_or_none(user.last_approval_end_at),
        count_eligibility_diagnoses=user.count_eligibility_diagnoses_iae + user.count_eligibility_diagnoses_geiq,
    )


def anonymized_jobapplication(obj):
    return AnonymizedApplication(
        job_seeker_birth_year=(
            obj.job_seeker.jobseeker_profile.birthdate.year if obj.job_seeker.jobseeker_profile.birthdate else None
        ),
        job_seeker_department_same_as_company_department=obj.job_seeker.department == obj.to_company.department,
        sender_kind=obj.sender_kind,
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
        had_been_transferred=obj.transferred_at is not None,
        number_of_jobs_applied_for=obj.number_of_jobs_applied_for,
        had_diagoriente_invitation=obj.diagoriente_invite_sent_at is not None,
        hiring_rome=obj.hired_job.appellation.rome if obj.hired_job else None,
        hiring_contract_type=obj.hired_job.contract_type if obj.hired_job else None,
        hiring_start_date=get_year_month_or_none(obj.hiring_start_at),
        had_approval=bool(obj.approval_id),
    )


def anonymized_approval(obj):
    return AnonymizedApproval(
        origin=obj.origin,
        origin_company_kind=obj.origin_siae_kind,
        origin_sender_kind=obj.origin_sender_kind,
        origin_prescriber_organization_kind=obj.origin_prescriber_organization_kind,
        start_at=get_year_month_or_none(obj.start_at),
        end_at=get_year_month_or_none(obj.end_at),
        had_eligibility_diagnosis=bool(obj.eligibility_diagnosis_id),
        number_of_prolongations=obj.number_of_prolongations,
        duration_of_prolongations=obj.duration_of_prolongations.days if obj.duration_of_prolongations else 0,
        number_of_suspensions=obj.number_of_suspensions,
        duration_of_suspensions=obj.duration_of_suspensions.days if obj.duration_of_suspensions else 0,
        number_of_job_applications=obj.number_of_job_applications,
        number_of_accepted_job_applications=obj.number_of_accepted_job_applications,
    )


def anonymized_eligibility_diagnosis(obj):
    data = {
        "created_at": get_year_month_or_none(obj.created_at),
        "expired_at": get_year_month_or_none(obj.expires_at),
        "job_seeker_birth_year": (
            obj.job_seeker.jobseeker_profile.birthdate.year if obj.job_seeker.jobseeker_profile.birthdate else None
        ),
        "job_seeker_department": obj.job_seeker.department,
        "author_kind": obj.author_kind,
        "author_prescriber_organization_kind": (
            obj.author_prescriber_organization.kind if obj.author_prescriber_organization else None
        ),
        "number_of_administrative_criteria": obj.number_of_administrative_criteria,
        "number_of_administrative_criteria_level_1": obj.number_of_administrative_criteria_level_1,
        "number_of_administrative_criteria_level_2": obj.number_of_administrative_criteria_level_2,
        "number_of_certified_administrative_criteria": obj.number_of_certified_administrative_criteria,
        "selected_administrative_criteria": obj.selected_administrative_criteria_list,
        "number_of_job_applications": obj.number_of_job_applications,
        "number_of_accepted_job_applications": obj.number_of_accepted_job_applications,
    }
    if isinstance(obj, EligibilityDiagnosis):
        data.update(
            {
                "author_siae_kind": obj.author_siae.kind if obj.author_siae else None,
                "number_of_approvals": obj.number_of_approvals,
                "first_approval_start_at": get_year_month_or_none(obj.first_approval_start_at),
                "last_approval_end_at": get_year_month_or_none(obj.last_approval_end_at),
            }
        )
        return AnonymizedSIAEEligibilityDiagnosis(**data)

    return AnonymizedGEIQEligibilityDiagnosis(**data)


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Perform the anonymization of job seekers",
        )

        parser.add_argument(
            "--batch-size",
            action="store",
            type=int,
            default=BATCH_SIZE,
            help="Number of job seekers to process in a batch",
        )

    def reset_notified_jobseekers_with_recent_activity(self):
        self.logger.info("Reseting inactive job seekers with recent activity")

        now = timezone.now()
        inactive_since = now - INACTIVITY_PERIOD

        reset_users_count = (
            User.objects.filter(kind=UserKind.JOB_SEEKER, upcoming_deletion_notified_at__isnull=False)
            .exclude(id__in=inactive_jobseekers_without_recent_related_objects(inactive_since, notified=True))
            .update(upcoming_deletion_notified_at=None)
        )

        self.logger.info("Reset notified job seekers with recent activity: %s", reset_users_count)

    @transaction.atomic
    def archive_jobseekers_after_grace_period(self):
        now = timezone.now()
        grace_period_since = now - GRACE_PERIOD
        self.logger.info("Anonymizing job seekers after grace period, notified before: %s", grace_period_since)

        # jobseekers
        users_to_archive = list(
            User.objects.filter(kind=UserKind.JOB_SEEKER, upcoming_deletion_notified_at__lte=grace_period_since)
            .annotate(
                count_accepted_applications=Count(
                    "job_applications__id", filter=Q(job_applications__state=JobApplicationState.ACCEPTED)
                ),
                count_IAE_applications=Count(
                    "job_applications__id", filter=Q(job_applications__to_company__kind__in=CompanyKind.siae_kinds())
                ),
                count_total_applications=Count("job_applications__id"),
                count_approvals=count_related_subquery(Approval, "user", "pk"),
                first_approval_start_at=Subquery(
                    Approval.objects.filter(user=OuterRef("pk"))
                    .values("user")
                    .annotate(first_approval_start_at=Min("start_at"))
                    .values("first_approval_start_at")
                ),
                last_approval_end_at=Subquery(
                    Approval.objects.filter(user=OuterRef("pk"))
                    .values("user")
                    .annotate(last_approval_end_at=Max("end_at"))
                    .values("last_approval_end_at")
                ),
                count_eligibility_diagnoses_iae=count_related_subquery(EligibilityDiagnosis, "job_seeker", "id"),
                count_eligibility_diagnoses_geiq=count_related_subquery(GEIQEligibilityDiagnosis, "job_seeker", "id"),
            )
            .order_by("upcoming_deletion_notified_at")[: self.batch_size]
        )

        anonymized_jobseekers = [anonymized_jobseeker(user) for user in users_to_archive]

        # job applications
        number_of_jobs_applied_for_count = count_related_subquery(
            JobDescription,
            "jobapplication",
            "pk",
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
                number_of_jobs_applied_for=number_of_jobs_applied_for_count,
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
        anonymized_jobapplications = [
            anonymized_jobapplication(job_application) for job_application in jobapplications_to_archive
        ]

        # approvals
        duration_of_prolongations_subquery = (
            Prolongation.objects.filter(approval=OuterRef("pk"))
            .values("approval")
            .annotate(duration_of_prolongations=Sum(F("end_at") - F("start_at")))
            .values("duration_of_prolongations")
        )
        duration_of_suspensions_subquery = (
            Suspension.objects.filter(approval=OuterRef("pk"))
            .values("approval")
            .annotate(duration_of_suspensions=Sum(F("end_at") - F("start_at")))
            .values("duration_of_suspensions")
        )

        approvals_to_archive = Approval.objects.filter(user__in=users_to_archive).annotate(
            number_of_prolongations=count_related_subquery(Prolongation, "approval", "pk"),
            duration_of_prolongations=Subquery(duration_of_prolongations_subquery),
            number_of_suspensions=count_related_subquery(Suspension, "approval", "pk"),
            duration_of_suspensions=Subquery(duration_of_suspensions_subquery),
            number_of_job_applications=count_related_subquery(JobApplication, "approval", "pk"),
            number_of_accepted_job_applications=count_related_subquery(
                JobApplication, "approval", "pk", extra_filters={"state": JobApplicationState.ACCEPTED}
            ),
        )

        anonymized_approvals = [anonymized_approval(approval) for approval in approvals_to_archive]

        # eligibility diagnoses
        # common subqueries
        common_eligibility_diag_annotations = dict(
            number_of_administrative_criteria=Count("selected_administrative_criteria"),
            number_of_administrative_criteria_level_1=Count(
                "selected_administrative_criteria",
                filter=Q(selected_administrative_criteria__administrative_criteria__level=1),
            ),
            number_of_administrative_criteria_level_2=Count(
                "selected_administrative_criteria",
                filter=Q(selected_administrative_criteria__administrative_criteria__level=2),
            ),
            number_of_certified_administrative_criteria=Count(
                "selected_administrative_criteria",
                filter=Q(selected_administrative_criteria__certified=True),
            ),
            selected_administrative_criteria_list=ArrayAgg(
                "administrative_criteria__kind", order_by=["administrative_criteria__kind"]
            ),
        )
        # IAE subqueries
        first_approval_start_at_subquery = (
            Approval.objects.filter(eligibility_diagnosis=OuterRef("pk"))
            .values("eligibility_diagnosis")
            .annotate(first_approval_start_at=Min("start_at"))
            .values("first_approval_start_at")
        )
        last_approval_end_at_subquery = (
            Approval.objects.filter(eligibility_diagnosis=OuterRef("pk"))
            .values("eligibility_diagnosis")
            .annotate(last_approval_end_at=Max("end_at"))
            .values("last_approval_end_at")
        )

        siae_eligibility_diagnoses_to_archive = (
            EligibilityDiagnosis.objects.filter(job_seeker__in=users_to_archive)
            .annotate(
                number_of_job_applications=count_related_subquery(JobApplication, "eligibility_diagnosis", "id"),
                number_of_accepted_job_applications=count_related_subquery(
                    JobApplication,
                    "eligibility_diagnosis",
                    "id",
                    extra_filters={"state": JobApplicationState.ACCEPTED},
                ),
                number_of_approvals=count_related_subquery(Approval, "eligibility_diagnosis", "id"),
                first_approval_start_at=Subquery(first_approval_start_at_subquery),
                last_approval_end_at=Subquery(last_approval_end_at_subquery),
                **common_eligibility_diag_annotations,
            )
            .select_related(
                "author_siae", "job_seeker", "job_seeker__jobseeker_profile", "author_prescriber_organization"
            )
        )
        anonymized_siae_eligibility_diagnoses = [
            anonymized_eligibility_diagnosis(eligibility_diagnosis)
            for eligibility_diagnosis in siae_eligibility_diagnoses_to_archive
        ]

        geiq_eligibility_diagnoses_to_archive = (
            GEIQEligibilityDiagnosis.objects.filter(job_seeker__in=users_to_archive)
            .annotate(
                number_of_job_applications=count_related_subquery(JobApplication, "geiq_eligibility_diagnosis", "id"),
                number_of_accepted_job_applications=count_related_subquery(
                    JobApplication,
                    "geiq_eligibility_diagnosis",
                    "id",
                    extra_filters={"state": JobApplicationState.ACCEPTED},
                ),
                **common_eligibility_diag_annotations,
            )
            .select_related(
                "author_geiq", "job_seeker", "job_seeker__jobseeker_profile", "author_prescriber_organization"
            )
        )
        anonymized_geiq_eligibility_diagnoses = [
            anonymized_eligibility_diagnosis(eligibility_diagnosis)
            for eligibility_diagnosis in geiq_eligibility_diagnoses_to_archive
        ]

        for user in users_to_archive:
            ArchiveUser(
                user,
            ).send()

        AnonymizedJobSeeker.objects.bulk_create(anonymized_jobseekers)
        AnonymizedApplication.objects.bulk_create(anonymized_jobapplications)
        AnonymizedApproval.objects.bulk_create(anonymized_approvals)
        AnonymizedSIAEEligibilityDiagnosis.objects.bulk_create(anonymized_siae_eligibility_diagnoses)
        AnonymizedGEIQEligibilityDiagnosis.objects.bulk_create(anonymized_geiq_eligibility_diagnoses)
        self._delete_jobapplications_with_related_objects(jobapplications_to_archive)
        approvals_to_archive.delete(enable_mass_delete=True)
        siae_eligibility_diagnoses_to_archive.delete()
        geiq_eligibility_diagnoses_to_archive.delete()
        self._delete_jobseekers_with_related_objects(users_to_archive)

        self.logger.info("Anonymized jobseekers after grace period, count: %d", len(anonymized_jobseekers))
        self.logger.info("Anonymized job applications after grace period, count: %d", len(anonymized_jobapplications))

    def _delete_jobseekers_with_related_objects(self, users):
        FollowUpGroup.objects.filter(beneficiary__in=users).delete()
        User.objects.filter(id__in=[user.id for user in users]).delete()
        for user in users:
            async_delete_contact(user.email)

    def _delete_jobapplications_with_related_objects(self, jobapplications):
        resume_pks = list(File.objects.filter(jobapplication__in=jobapplications).values_list("pk", flat=True))
        EmployeeRecord.objects.filter(job_application__in=jobapplications).delete()
        jobapplications.delete()
        File.objects.filter(pk__in=resume_pks).delete()

    @monitor(
        monitor_slug="anonymize_jobseekers",
        monitor_config={
            "schedule": {"type": "crontab", "value": "*/20 7-18 * * MON-FRI"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 2,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    @dry_runnable
    def handle(self, *args, batch_size, **options):
        if settings.SUSPEND_ANONYMIZE_JOBSEEKERS:
            self.logger.info("Anonymizing job seekers is suspended, exiting command")
            return

        self.batch_size = batch_size
        self.logger.info("Start anonymizing job seekers")

        self.reset_notified_jobseekers_with_recent_activity()
        self.archive_jobseekers_after_grace_period()
