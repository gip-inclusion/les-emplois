from datetime import datetime, timezone

import factory
import factory.fuzzy
from dateutil.relativedelta import relativedelta

from itou.companies.enums import CompanyKind
from itou.companies.models import JobDescription
from itou.eligibility.enums import AuthorKind
from itou.job_applications import models
from itou.job_applications.enums import Prequalification, ProfessionalSituationExperience, SenderKind
from itou.jobs.models import Appellation
from itou.utils.types import InclusiveDateRange
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import EligibilityDiagnosisFactory, GEIQEligibilityDiagnosisFactory
from tests.prescribers.factories import (
    PrescriberOrganizationWithMembershipFactory,
    PrescriberPoleEmploiWithMembershipFactory,
)
from tests.users.factories import (
    JobSeekerFactory,
    JobSeekerWithAddressFactory,
    PrescriberFactory,
)


class JobApplicationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.JobApplication
        skip_postgeneration_save = True

    class Params:
        job_seeker_with_address = factory.Trait(
            job_seeker=factory.SubFactory(JobSeekerWithAddressFactory, with_mocked_address=True)
        )
        with_approval = factory.Trait(
            state=models.JobApplicationWorkflow.STATE_ACCEPTED,
            approval=factory.SubFactory(
                ApprovalFactory,
                user=factory.SelfAttribute("..job_seeker"),
                eligibility_diagnosis=factory.SelfAttribute("..eligibility_diagnosis"),
            ),
        )
        # GEIQ diagnosis created by a GEIQ
        with_geiq_eligibility_diagnosis = factory.Trait(
            to_company=factory.SubFactory(CompanyFactory, with_membership=True, kind=CompanyKind.GEIQ),
            sender=factory.LazyAttribute(lambda obj: obj.to_company.members.first()),
            geiq_eligibility_diagnosis=factory.SubFactory(
                GEIQEligibilityDiagnosisFactory,
                job_seeker=factory.SelfAttribute("..job_seeker"),
                author=factory.SelfAttribute("..sender"),
                author_kind=AuthorKind.GEIQ,
                author_geiq=factory.SelfAttribute("..to_company"),
            ),
            eligibility_diagnosis=None,
        )
        with_geiq_eligibility_diagnosis_from_prescriber = factory.Trait(
            to_company=factory.SubFactory(CompanyFactory, with_membership=True, kind=CompanyKind.GEIQ),
            sender=factory.LazyAttribute(lambda obj: obj.sender_prescriber_organization.members.first()),
            geiq_eligibility_diagnosis=factory.SubFactory(
                GEIQEligibilityDiagnosisFactory,
                job_seeker=factory.SelfAttribute("..job_seeker"),
                author=factory.SelfAttribute("..sender"),
                author_kind=AuthorKind.PRESCRIBER,
                author_prescriber_organization=factory.SubFactory(
                    PrescriberOrganizationWithMembershipFactory, authorized=True
                ),
            ),
            eligibility_diagnosis=None,
        )
        sent_by_authorized_prescriber_organisation = factory.Trait(
            sender_prescriber_organization=factory.SubFactory(
                PrescriberOrganizationWithMembershipFactory, authorized=True
            ),
            sender=factory.LazyAttribute(lambda obj: obj.sender_prescriber_organization.members.first()),
            sender_kind=SenderKind.PRESCRIBER,
        )
        for_snapshot = factory.Trait(
            pk="11111111-1111-1111-1111-111111111111",
            to_company__for_snapshot=True,
        )

    job_seeker = factory.SubFactory(JobSeekerFactory)
    to_company = factory.SubFactory(CompanyFactory, with_membership=True)
    message = factory.Faker("sentence", nb_words=40)
    answer = factory.Faker("sentence", nb_words=40)
    hiring_start_at = factory.LazyFunction(lambda: datetime.now(timezone.utc).date())
    hiring_end_at = factory.LazyFunction(lambda: datetime.now(timezone.utc).date() + relativedelta(years=2))
    resume_link = "https://server.com/rockie-balboa.pdf"
    sender_kind = SenderKind.PRESCRIBER  # Make explicit the model's default value
    sender = factory.SubFactory(PrescriberFactory)
    eligibility_diagnosis = factory.SubFactory(
        EligibilityDiagnosisFactory,
        job_seeker=factory.SelfAttribute("..job_seeker"),
        author=factory.SelfAttribute("..sender"),
    )

    @factory.post_generation
    def selected_jobs(self, create, extracted, **kwargs):
        """
        Add selected_jobs in which the job seeker is interested.
        https://factoryboy.readthedocs.io/en/latest/recipes.html#simple-many-to-many-relationship

        Usage:
            appellation1 = Appellation.objects.filter(code='10933')
            appellation2 = Appellation.objects.filter(code='10934')
            JobApplicationFactory(selected_jobs=(appellation1, appellation2))
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


class PriorActionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.PriorAction

    job_application = factory.SubFactory(JobApplicationFactory)
    action = factory.fuzzy.FuzzyChoice(Prequalification.values + ProfessionalSituationExperience.values)
    dates = factory.LazyFunction(
        lambda: InclusiveDateRange(
            datetime.now(timezone.utc).date(),
            datetime.now(timezone.utc).date() + relativedelta(years=2),
        )
    )


class JobApplicationSentByJobSeekerFactory(JobApplicationFactory):
    """Generates a JobApplication() object sent by a job seeker."""

    sender = factory.SelfAttribute("job_seeker")
    sender_kind = SenderKind.JOB_SEEKER


class JobApplicationSentByCompanyFactory(JobApplicationFactory):
    """Generates a JobApplication() object sent by a company."""

    sender_kind = SenderKind.EMPLOYER
    # Currently a company can only postulate for itself,
    # this is the default behavior here.
    sender_company = factory.SelfAttribute("to_company")
    sender = factory.LazyAttribute(lambda obj: obj.to_company.members.first())


class JobApplicationSentByPrescriberFactory(JobApplicationFactory):
    """Generates a JobApplication() object sent by a prescriber."""

    sender = factory.SubFactory(PrescriberFactory)
    sender_kind = SenderKind.PRESCRIBER


class JobApplicationSentByPrescriberOrganizationFactory(JobApplicationSentByPrescriberFactory):
    """Generates a JobApplication() object sent by a prescriber member of an organization."""

    sender_prescriber_organization = factory.SubFactory(PrescriberOrganizationWithMembershipFactory)
    sender = factory.LazyAttribute(lambda obj: obj.sender_prescriber_organization.members.first())


class JobApplicationSentByPrescriberPoleEmploiFactory(JobApplicationSentByPrescriberFactory):
    """Generates a JobApplication() object sent by a prescriber member of Pôle emploi organization."""

    sender_prescriber_organization = factory.SubFactory(PrescriberPoleEmploiWithMembershipFactory)
    sender = factory.LazyAttribute(lambda obj: obj.sender_prescriber_organization.members.first())


class JobApplicationWithoutApprovalFactory(JobApplicationSentByPrescriberFactory):
    """Generates a JobApplication() object without an Approval() object."""

    state = models.JobApplicationWorkflow.STATE_ACCEPTED
    hiring_without_approval = True


class JobApplicationWithApprovalNotCancellableFactory(JobApplicationFactory):
    with_approval = True
    hiring_start_at = factory.LazyFunction(lambda: datetime.now(timezone.utc).date() - relativedelta(days=5))
    hiring_end_at = factory.LazyFunction(lambda: datetime.now(timezone.utc).date() + relativedelta(years=2, days=-5))


class JobApplicationWithCompleteJobSeekerProfileFactory(JobApplicationWithApprovalNotCancellableFactory):
    """
    This job application has a jobseeker with a COMPLETE job seeker profile

    Suitable for employee records tests
    """

    job_seeker = factory.SubFactory(
        JobSeekerWithAddressFactory,
        with_mocked_address=True,
        jobseeker_profile__with_hexa_address=True,
        jobseeker_profile__with_education_level=True,
        born_in_france=True,
    )
    sender_prescriber_organization = factory.SubFactory(PrescriberOrganizationWithMembershipFactory)
