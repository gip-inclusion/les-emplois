import uuid
from datetime import UTC, datetime

import factory
import factory.fuzzy
from dateutil.relativedelta import relativedelta
from django.core.files.storage import storages

from itou.companies.enums import CompanyKind
from itou.companies.models import JobDescription
from itou.eligibility.enums import AuthorKind
from itou.job_applications import models
from itou.job_applications.enums import (
    JobApplicationState,
    Prequalification,
    ProfessionalSituationExperience,
    SenderKind,
)
from itou.jobs.models import Appellation
from itou.users.enums import ActionKind
from itou.utils.types import InclusiveDateRange
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory, JobDescriptionFactory
from tests.eligibility.factories import (
    GEIQEligibilityDiagnosisFactory,
    IAEEligibilityDiagnosisFactory,
)
from tests.files.factories import FileFactory
from tests.prescribers.factories import (
    PrescriberMembershipFactory,
    PrescriberOrganizationFactory,
)
from tests.users.factories import (
    EmployerFactory,
    JobSeekerAssignmentFactory,
    JobSeekerFactory,
    PrescriberFactory,
)
from tests.utils.factory_boy import AutoNowOverrideMixin


class JobApplicationFactory(AutoNowOverrideMixin, factory.django.DjangoModelFactory):
    class Meta:
        model = models.JobApplication
        skip_postgeneration_save = True

    class Params:
        # attributes used in Traits
        sender_is_job_seeker = factory.LazyAttribute(lambda o: o.sender_kind == SenderKind.JOB_SEEKER)
        # Sender ------------------------------------------------------------------------------------------------------
        sent_by_job_seeker = factory.Trait(
            sender_kind=SenderKind.JOB_SEEKER,
            sender=factory.SelfAttribute("job_seeker"),
        )
        sent_by_prescriber_alone = factory.Trait(
            sender=factory.SubFactory(PrescriberFactory),
            sender_kind=SenderKind.PRESCRIBER,
        )
        sent_by_prescriber = factory.Trait(
            sender_prescriber_organization=factory.SubFactory(PrescriberOrganizationFactory, with_membership=True),
            sender=factory.LazyAttribute(
                lambda obj: (
                    obj.sender_prescriber_organization.members.first()
                    or PrescriberMembershipFactory(organization=obj.sender_presciber_organization).user
                )
            ),
            sender_kind=SenderKind.PRESCRIBER,
        )
        sent_by_authorized_prescriber = factory.Trait(
            sent_by_prescriber=True,
            sender_prescriber_organization__authorized=True,
        )
        sent_by_employer = factory.Trait(
            sender_kind=SenderKind.EMPLOYER,
            sender_company=factory.SelfAttribute("to_company"),
            sender=factory.LazyAttribute(
                lambda obj: (
                    obj.sender_company.members.first() or CompanyMembershipFactory(company=obj.sender_company).user
                )
            ),
        )
        sent_by_another_employer = factory.Trait(
            sent_by_employer=True,
            sender_company=factory.SubFactory(CompanyFactory, with_membership=True),
        )
        # IAE ---------------------------------------------------------------------------------------------------------
        with_iae_eligibility_diagnosis = factory.Trait(
            state=JobApplicationState.ACCEPTED,
            eligibility_diagnosis=factory.SubFactory(
                IAEEligibilityDiagnosisFactory,
                from_prescriber=True,
                job_seeker=factory.SelfAttribute("..job_seeker"),
                author=factory.Maybe(
                    "..sender_is_job_seeker",
                    yes_declaration=factory.SubFactory(PrescriberFactory),
                    no_declaration=factory.SelfAttribute("..sender"),
                ),
            ),
            to_company=factory.SubFactory(CompanyFactory, with_membership=True, subject_to_iae_rules=True),
        )
        with_approval = factory.Trait(
            state=JobApplicationState.ACCEPTED,
            with_iae_eligibility_diagnosis=True,
            approval=factory.SubFactory(
                ApprovalFactory,
                user=factory.SelfAttribute("..job_seeker"),
                eligibility_diagnosis=factory.Maybe(
                    "for_snapshot", no_declaration=factory.SelfAttribute("..eligibility_diagnosis")
                ),
            ),
        )
        # GEIQ --------------------------------------------------------------------------------------------------------
        with_geiq_eligibility_diagnosis_from_employer = factory.Trait(
            state=JobApplicationState.ACCEPTED,
            sent_by_employer=True,
            to_company=factory.SubFactory(CompanyFactory, with_membership=True, kind=CompanyKind.GEIQ),
            geiq_eligibility_diagnosis=factory.SubFactory(
                GEIQEligibilityDiagnosisFactory,
                job_seeker=factory.SelfAttribute("..job_seeker"),
                author=factory.SelfAttribute("..sender"),
                author_kind=AuthorKind.GEIQ,
                author_geiq=factory.SelfAttribute("..to_company"),
            ),
        )
        with_geiq_eligibility_diagnosis_from_prescriber = factory.Trait(
            state=JobApplicationState.ACCEPTED,
            sent_by_authorized_prescriber=True,
            to_company=factory.SubFactory(CompanyFactory, with_membership=True, kind=CompanyKind.GEIQ),
            geiq_eligibility_diagnosis=factory.SubFactory(
                GEIQEligibilityDiagnosisFactory,
                job_seeker=factory.SelfAttribute("..job_seeker"),
                author=factory.SelfAttribute("..sender"),
                author_kind=AuthorKind.PRESCRIBER,
                author_prescriber_organization=factory.SelfAttribute("..sender_prescriber_organization"),
            ),
        )
        # other -------------------------------------------------------------------------------------------------------
        was_hired = factory.Trait(
            state=JobApplicationState.ACCEPTED,
            to_company__with_jobs=True,
            hired_job=factory.SubFactory(JobDescriptionFactory, company=factory.SelfAttribute("..to_company")),
        )
        for_employee_record = factory.Trait(
            with_approval=True,
            sent_by_prescriber=True,
            job_seeker=factory.SubFactory(
                JobSeekerFactory,
                with_mocked_address=True,
                jobseeker_profile__with_hexa_address=True,
                jobseeker_profile__with_education_level=True,
                born_in_france=True,
            ),
        )
        for_snapshot = factory.Trait(
            pk=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            message="Message de candidature",
            to_company__for_snapshot=True,
            sender__for_snapshot=True,
            job_seeker__for_snapshot=True,
            approval__for_snapshot=True,
        )

    job_seeker = factory.SubFactory(JobSeekerFactory)
    to_company = factory.SubFactory(CompanyFactory, with_membership=True)
    message = factory.Faker("sentence", nb_words=40)
    answer = factory.Faker("sentence", nb_words=40)
    hiring_start_at = factory.LazyFunction(lambda: datetime.now(UTC).date())
    hiring_end_at = factory.LazyFunction(lambda: datetime.now(UTC).date() + relativedelta(years=2))
    resume = factory.SubFactory(FileFactory)
    sender_kind = None  # Force all calls to use a sent_by_xxx trait as the db doesn't allow null values
    processed_at = factory.LazyAttribute(
        lambda o: (
            datetime.now(UTC)
            if str(o.state) in models.JobApplicationWorkflow.JOB_APPLICATION_PROCESSED_STATES
            else None
        )
    )

    @classmethod
    def _generate(cls, strategy, params):
        kinds = [
            "sent_by_job_seeker",
            "sent_by_prescriber",
            "sent_by_prescriber_alone",
            "sent_by_employer",
            "sent_by_another_employer",
            "sent_by_authorized_prescriber",
        ]
        given_kinds = [kind for kind in kinds if params.get(kind)]
        if len(given_kinds) != 1:
            raise ValueError(f"Bad sent_by_xxx trait count {given_kinds}")

        if "sender_kind" in params:
            raise ValueError("sender_kind is not allowed in params")
        return super()._generate(strategy, params)

    @factory.post_generation
    def selected_jobs(self, create, extracted, **kwargs):
        """
        Add selected_jobs in which the job seeker is interested.
        https://factoryboy.readthedocs.io/en/latest/recipes.html#simple-many-to-many-relationship

        Usage:
            appellation1 = Appellation.objects.filter(code='10933')
            appellation2 = Appellation.objects.filter(code='10934')
            JobApplicationFactory(sent_by_prescriber_alone=True,selected_jobs=(appellation1, appellation2))
        """
        if not create:
            # Simple build, do nothing.
            return

        if extracted:
            # A list of jobs were passed in, use them.
            for job_description in extracted:
                if isinstance(job_description, Appellation):
                    job_description, _ = JobDescription.objects.get_or_create(
                        company=self.to_company, appellation=job_description
                    )
                self.selected_jobs.add(job_description)

    @factory.post_generation
    def with_file(self, create, extracted, **kwargs):
        if create and extracted:
            public_storage = storages["public"]
            public_storage.save(self.resume.key, extracted)

    @factory.post_generation
    def with_job_seeker_assignment(self, create, extracted, **kwargs):
        # Hook that creates a JobSeekerAssignment. We want to keep it
        # simple, but bear in mind that there is a unique constraint
        # on the job seeker/prescriber couple. If you create multiple
        # matching job applications `with_job_seeker_assignment=True`,
        # that will break.
        if not create:  # build only, do nothing
            return
        if extracted:
            JobSeekerAssignmentFactory(
                updated_at=self.created_at,
                job_seeker=self.job_seeker,
                professional=self.sender,
                prescriber_organization=self.sender_prescriber_organization,
                last_action_kind=ActionKind.APPLY,
            )


class PriorActionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.PriorAction

    job_application = factory.SubFactory(JobApplicationFactory)
    action = factory.fuzzy.FuzzyChoice(Prequalification.values + ProfessionalSituationExperience.values)
    dates = factory.LazyFunction(
        lambda: InclusiveDateRange(
            datetime.now(UTC).date(),
            datetime.now(UTC).date() + relativedelta(years=2),
        )
    )


class JobApplicationCommentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.JobApplicationComment

    class Params:
        for_snapshot = factory.Trait(
            job_application__for_snapshot=True,
            created_at=datetime(2000, 1, 1, 12, 12, 0, tzinfo=UTC),
            created_by__for_snapshot=True,
            message="Cette candidate est venue 3 fois, elle est motivée.",
        )

    job_application = factory.SubFactory(JobApplicationFactory)
    created_at = factory.LazyFunction(datetime.now)
    created_by = factory.SubFactory(EmployerFactory)  # Usually a member of the company, but he might have left
    message = factory.Faker("sentence", nb_words=40)
    company = factory.SelfAttribute(".job_application.to_company")
