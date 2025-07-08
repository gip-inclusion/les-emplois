from django.conf import settings
from django.contrib.postgres.aggregates import ArrayAgg
from django.db import transaction
from django.db.models import Count, F, Max, Min, OuterRef, Q, Subquery, Sum
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou import eligibility
from itou.approvals.models import Approval, Prolongation, Suspension
from itou.archive.models import (
    AnonymizedApplication,
    AnonymizedApproval,
    AnonymizedGEIQEligibilityDiagnosis,
    AnonymizedJobSeeker,
    AnonymizedSIAEEligibilityDiagnosis,
)
from itou.archive.tasks import async_delete_contact
from itou.archive.utils import count_related_subquery, get_year_month_or_none
from itou.companies.enums import CompanyKind
from itou.companies.models import JobDescription
from itou.eligibility.models import EligibilityDiagnosis
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.files.models import File
from itou.gps.models import FollowUpGroup
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication, JobApplicationTransitionLog
from itou.users.models import User, UserKind
from itou.users.notifications import ArchiveUser
from itou.utils.command import BaseCommand
from itou.utils.constants import GRACE_PERIOD


BATCH_SIZE = 100


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
        count_approvals=user.count_approvals or 0,
        first_approval_start_at=get_year_month_or_none(user.first_approval_start_at),
        last_approval_end_at=get_year_month_or_none(user.last_approval_end_at),
        count_eligibility_diagnoses=user.count_eligibility_diagnoses or 0,
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
        has_been_transferred=obj.transferred_at is not None,
        number_of_jobs_applied_for=obj.number_of_jobs_applied_for or 0,
        has_diagoriente_invitation=obj.diagoriente_invite_sent_at is not None,
        hiring_rome=obj.hired_job.appellation.rome if obj.hired_job else None,
        hiring_contract_type=obj.hired_job.contract_type if obj.hired_job else None,
        hiring_contract_nature=obj.hired_job.contract_nature if obj.hired_job else None,
        hiring_start_date=get_year_month_or_none(obj.hiring_start_at),
        has_approval=False if obj.approval_id is None else True,
    )


def anonymized_approval(obj):
    return AnonymizedApproval(
        origin=obj.origin,
        origin_company_kind=obj.origin_siae_kind,
        origin_sender_kind=obj.origin_sender_kind,
        origin_prescriber_organization_kind=obj.origin_prescriber_organization_kind,
        start_at=get_year_month_or_none(obj.start_at),
        end_at=get_year_month_or_none(obj.end_at),
        had_eligibility_diagnosis=False if obj.eligibility_diagnosis_id is None else True,
        number_of_prolongations=obj.number_of_prolongations or 0,
        duration_of_prolongations=obj.duration_of_prolongations.days if obj.duration_of_prolongations else 0,
        number_of_suspensions=obj.number_of_suspensions or 0,
        duration_of_suspensions=obj.duration_of_suspensions.days if obj.duration_of_suspensions else 0,
        number_of_job_applications=obj.number_of_job_applications or 0,
        number_of_accepted_job_applications=obj.number_of_accepted_job_applications or 0,
    )


def anonymized_eligibility_diagnosis(obj, model, siae_extra_fields=False):
    data = dict(
        created_at=get_year_month_or_none(obj.created_at),
        expired_at=get_year_month_or_none(obj.expires_at),
        job_seeker_birth_year=(
            obj.job_seeker.jobseeker_profile.birthdate.year if obj.job_seeker.jobseeker_profile.birthdate else None
        ),
        job_seeker_department=obj.job_seeker.department,
        job_seeker_had_pole_emploi_id=bool(obj.job_seeker.jobseeker_profile.pole_emploi_id),
        job_seeker_had_nir=bool(obj.job_seeker.jobseeker_profile.nir),
        author_kind=obj.author_kind,
        author_prescriber_organization_kind=(
            obj.author_prescriber_organization.kind if obj.author_prescriber_organization else None
        ),
        number_of_administrative_criteria=obj.number_of_administrative_criteria or 0,
        number_of_administrative_criteria_level_1=obj.number_of_administrative_criteria_level_1 or 0,
        number_of_administrative_criteria_level_2=obj.number_of_administrative_criteria_level_2 or 0,
        number_of_certified_administrative_criteria=obj.number_of_certified_administrative_criteria or 0,
        selected_administrative_criteria=obj.selected_administrative_criteria_list,
        number_of_job_applications=obj.number_of_job_applications if obj.number_of_job_applications else 0,
        number_of_accepted_job_applications=obj.number_of_accepted_job_applications
        if obj.number_of_accepted_job_applications
        else 0,
    )
    if siae_extra_fields:
        data.update(
            {
                "author_siae_kind": obj.author_siae.kind if obj.author_siae else None,
                "number_of_approvals": obj.number_of_approvals or 0,
                "first_approval_start_at": get_year_month_or_none(obj.first_approval_start_at),
                "last_approval_end_at": get_year_month_or_none(obj.last_approval_end_at),
            }
        )
    return model(**data)


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
                count_eligibility_diagnoses=count_related_subquery(EligibilityDiagnosis, "job_seeker", "id"),
            )
            .order_by("upcoming_deletion_notified_at")[: self.batch_size]
        )

        archived_jobseekers = [anonymized_jobseeker(user) for user in users_to_archive]

        # job applications
        number_of_jobs_applied_for_subquery = count_related_subquery(
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

        # approvals
        number_of_prolongations_subquery = count_related_subquery(
            Prolongation,
            "approval",
            "pk",
        )
        duration_of_prolongations_subquery = (
            Prolongation.objects.filter(approval=OuterRef("pk"))
            .values("approval")
            .annotate(duration_of_prolongations=Sum(F("end_at") - F("start_at")))
            .values("duration_of_prolongations")
        )
        number_of_suspensions_subquery = count_related_subquery(
            Suspension,
            "approval",
            "pk",
        )
        duration_of_suspensions_subquery = (
            Suspension.objects.filter(approval=OuterRef("pk"))
            .values("approval")
            .annotate(duration_of_suspensions=Sum(F("end_at") - F("start_at")))
            .values("duration_of_suspensions")
        )
        number_of_job_applications_subquery = count_related_subquery(
            JobApplication,
            "approval",
            "pk",
        )
        number_of_accepted_job_applications_subquery = count_related_subquery(
            JobApplication,
            "approval",
            "pk",
            extra_filters={"state": JobApplicationState.ACCEPTED},
        )

        approvals_to_archive = Approval.objects.filter(user__in=users_to_archive).annotate(
            number_of_prolongations=Subquery(number_of_prolongations_subquery),
            duration_of_prolongations=Subquery(duration_of_prolongations_subquery),
            number_of_suspensions=Subquery(number_of_suspensions_subquery),
            duration_of_suspensions=Subquery(duration_of_suspensions_subquery),
            number_of_job_applications=Subquery(number_of_job_applications_subquery),
            number_of_accepted_job_applications=Subquery(number_of_accepted_job_applications_subquery),
        )

        anonymized_jobapplications = [anonymized_approval(approval) for approval in approvals_to_archive]

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
            number_of_job_applications=Subquery(count_related_subquery(JobApplication, "eligibility_diagnosis", "id")),
            number_of_accepted_job_applications=Subquery(
                count_related_subquery(
                    JobApplication,
                    "eligibility_diagnosis",
                    "id",
                    extra_filters={"state": JobApplicationState.ACCEPTED},
                )
            ),
        )
        # IAE subqueries
        number_of_approvals_subquery = count_related_subquery(Approval, "eligibility_diagnosis", "id")
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
                number_of_approvals=Subquery(number_of_approvals_subquery),
                first_approval_start_at=Subquery(first_approval_start_at_subquery),
                last_approval_end_at=Subquery(last_approval_end_at_subquery),
                **common_eligibility_diag_annotations,
            )
            .select_related(
                "author_siae", "job_seeker", "job_seeker__jobseeker_profile", "author_prescriber_organization"
            )
        )
        anonymized_siae_eligibility_diagnoses = [
            anonymized_eligibility_diagnosis(
                eligibility_diagnosis,
                model=AnonymizedSIAEEligibilityDiagnosis,
                siae_extra_fields=True,
            )
            for eligibility_diagnosis in siae_eligibility_diagnoses_to_archive
        ]

        geiq_eligibility_diagnoses_to_archive = (
            GEIQEligibilityDiagnosis.objects.filter(job_seeker__in=users_to_archive)
            .annotate(**common_eligibility_diag_annotations)
            .select_related(
                "author_geiq", "job_seeker", "job_seeker__jobseeker_profile", "author_prescriber_organization"
            )
        )
        anonymized_geiq_eligibility_diagnoses = [
            anonymized_eligibility_diagnosis(
                eligibility_diagnosis,
                model=AnonymizedGEIQEligibilityDiagnosis,
            )
            for eligibility_diagnosis in geiq_eligibility_diagnoses_to_archive
        ]

        if self.wet_run:
            for user in users_to_archive:
                ArchiveUser(
                    user,
                ).send()

            AnonymizedJobSeeker.objects.bulk_create(archived_jobseekers)
            AnonymizedApplication.objects.bulk_create(archived_jobapplications)
            AnonymizedApproval.objects.bulk_create(anonymized_jobapplications)
            AnonymizedSIAEEligibilityDiagnosis.objects.bulk_create(anonymized_siae_eligibility_diagnoses)
            AnonymizedGEIQEligibilityDiagnosis.objects.bulk_create(anonymized_geiq_eligibility_diagnoses)
            self._delete_jobapplications_with_related_objects(jobapplications_to_archive)
            approvals_to_archive.delete(enable_mass_delete=True)
            siae_eligibility_diagnoses_to_archive.delete()
            geiq_eligibility_diagnoses_to_archive.delete()
            self._delete_jobseekers_with_related_objects(users_to_archive)

        self.logger.info("Anonymized jobseekers after grace period, count: %d", len(archived_jobseekers))
        self.logger.info("Anonymized job applications after grace period, count: %d", len(archived_jobapplications))

    def _delete_jobseekers_with_related_objects(self, users):
        FollowUpGroup.objects.filter(beneficiary__in=users).delete()
        User.objects.filter(id__in=[user.id for user in users]).delete()
        for user in users:
            async_delete_contact(user.email)

    def _delete_jobapplications_with_related_objects(self, jobapplications):
        File.objects.filter(deleted_at__isnull=True, jobapplication__in=jobapplications).update(
            deleted_at=timezone.now()
        )
        jobapplications.delete()

    @monitor(
        monitor_slug="anonymize_jobseekers",
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
        if settings.SUSPEND_ANONYMIZE_JOBSEEKERS:
            self.logger.info("Anonymizing job seekers is suspended, exiting command")
            return

        self.wet_run = wet_run
        self.batch_size = batch_size
        self.logger.info("Start anonymizing job seekers in %s mode", "wet_run" if wet_run else "dry_run")

        self.reset_notified_jobseekers_with_recent_activity()
        self.archive_jobseekers_after_grace_period()
