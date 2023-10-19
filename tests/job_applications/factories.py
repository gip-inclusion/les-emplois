from datetime import datetime, timezone

import factory
import factory.fuzzy
from dateutil.relativedelta import relativedelta

from itou.companies.enums import SiaeKind
from itou.companies.models import SiaeJobDescription
from itou.eligibility.enums import AuthorKind
from itou.job_applications import models
from itou.job_applications.enums import Prequalification, ProfessionalSituationExperience, SenderKind
from itou.jobs.models import Appellation
from itou.utils.types import InclusiveDateRange
from tests.approvals.factories import ApprovalFactory
from tests.asp.factories import CommuneFactory, CountryFranceFactory
from tests.companies.factories import SiaeFactory
from tests.eligibility.factories import EligibilityDiagnosisFactory, GEIQEligibilityDiagnosisFactory
from tests.prescribers.factories import (
    PrescriberOrganizationWithMembershipFactory,
    PrescriberPoleEmploiWithMembershipFactory,
)
from tests.users.factories import (
    JobSeekerFactory,
    JobSeekerProfileWithHexaAddressFactory,
    JobSeekerWithMockedAddressFactory,
    PrescriberFactory,
)


class JobApplicationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.JobApplication
        skip_postgeneration_save = True

    class Params:
        job_seeker_with_address = factory.Trait(job_seeker=factory.SubFactory(JobSeekerWithMockedAddressFactory))
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
            to_siae=factory.SubFactory(SiaeFactory, with_membership=True, kind=SiaeKind.GEIQ),
            sender=factory.LazyAttribute(lambda obj: obj.to_siae.members.first()),
            geiq_eligibility_diagnosis=factory.SubFactory(
                GEIQEligibilityDiagnosisFactory,
                job_seeker=factory.SelfAttribute("..job_seeker"),
                author=factory.SelfAttribute("..sender"),
                author_kind=AuthorKind.GEIQ,
                author_geiq=factory.SelfAttribute("..to_siae"),
            ),
            eligibility_diagnosis=None,
        )
        with_geiq_eligibility_diagnosis_from_prescriber = factory.Trait(
            to_siae=factory.SubFactory(SiaeFactory, with_membership=True, kind=SiaeKind.GEIQ),
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

    job_seeker = factory.SubFactory(JobSeekerFactory)
    to_siae = factory.SubFactory(SiaeFactory, with_membership=True)
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
            for siae_job_description in extracted:
                if isinstance(siae_job_description, Appellation):
                    siae_job_description, _ = SiaeJobDescription.objects.get_or_create(
                        siae=self.to_siae, appellation=siae_job_description
                    )
                self.selected_jobs.add(siae_job_description)


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


class JobApplicationSentBySiaeFactory(JobApplicationFactory):
    """Generates a JobApplication() object sent by an Siae."""

    sender_kind = SenderKind.EMPLOYER
    # Currently an Siae can only postulate for itself,
    # this is the default behavior here.
    sender_siae = factory.SelfAttribute("to_siae")
    sender = factory.LazyAttribute(lambda obj: obj.to_siae.members.first())


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

    job_seeker = factory.SubFactory(JobSeekerWithMockedAddressFactory)
    sender_prescriber_organization = factory.SubFactory(PrescriberOrganizationWithMembershipFactory)

    @factory.post_generation
    def set_job_seeker_profile(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return
        # Create a profile for current user
        # NOTE(vperron): We have to remove the profile after its creation because our new behaviour in User.save()
        # forces us to have a JobSeekerProfile ready, immediately. We don't want to adapt the save() to handle a
        # case that can only happen in tests though.
        self.job_seeker.jobseeker_profile.delete()
        self.job_seeker.jobseeker_profile = JobSeekerProfileWithHexaAddressFactory(
            user=self.job_seeker,
            birth_place=CommuneFactory(),
            birth_country=CountryFranceFactory(),
        )

        self.job_seeker.save()
