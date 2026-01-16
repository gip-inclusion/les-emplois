from datetime import timedelta

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.models import GEIQSelectedAdministrativeCriteria, SelectedAdministrativeCriteria
from itou.eligibility.tasks import API_PARTICULIER_RETRY_DURATION, async_certify_criterion_with_api_particulier
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication
from itou.utils.apis import api_particulier
from itou.utils.command import BaseCommand
from itou.utils.db import or_queries


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @dry_runnable
    def handle(self, **options):
        for model, diagnosis_accessor in [
            (SelectedAdministrativeCriteria, "eligibility_diagnosis_id"),
            (GEIQSelectedAdministrativeCriteria, "geiq_eligibility_diagnosis_id"),
        ]:
            self.retry_api_particulier_criteria(model, diagnosis_accessor)

    def retry_api_particulier_criteria(self, model, diagnosis_accessor):
        now = timezone.now()
        today = timezone.localdate(now)
        profile_required_fields = api_particulier.JOBSEEKER_PROFILE_REQUIRED_FIELDS.copy()
        # birth_country and birthdate are sufficient to tell if the job seeker
        # can be certified. birth_place is only specified when birth_country is
        # France, removing the field makes the query simpler.
        profile_required_fields.remove("birth_place")
        to_recertify = (
            model.objects.filter(
                administrative_criteria__kind__in=AdministrativeCriteriaKind.certifiable_by_api_particulier(),
                certification_period=None,
                eligibility_diagnosis__expires_at__gte=today,
                created_at__lte=now - API_PARTICULIER_RETRY_DURATION,
            )
            .exclude(
                or_queries(
                    [
                        Exists(
                            JobApplication.objects.filter(
                                state=JobApplicationState.ACCEPTED,
                                hiring_start_at__lte=today,
                                **{diagnosis_accessor: OuterRef("eligibility_diagnosis_id")},
                            )
                        ),
                        *[
                            Q(**{f"eligibility_diagnosis__job_seeker__{field}": ""})
                            for field in api_particulier.USER_REQUIRED_FIELDS
                        ],
                        *[
                            Q(**{f"eligibility_diagnosis__job_seeker__jobseeker_profile__{field}": None})
                            for field in profile_required_fields
                        ],
                        Q(last_certification_attempt_at__gte=now - timedelta(days=7)),
                    ],
                )
            )
            .order_by("pk")
        )
        for criterion in to_recertify:
            async_certify_criterion_with_api_particulier(criterion._meta.model_name, criterion.pk)
