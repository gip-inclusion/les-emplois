import factory
import factory.fuzzy
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from itou.approvals.factories import ApprovalFactory
from itou.eligibility.factories import EligibilityDiagnosisFactory
from itou.job_applications import models
from itou.job_applications.enums import SenderKind
from itou.jobs.models import Appellation
from itou.prescribers.factories import (
    PrescriberOrganizationWithMembershipFactory,
    PrescriberPoleEmploiWithMembershipFactory,
)
from itou.siaes.factories import SiaeFactory
from itou.siaes.models import SiaeJobDescription
from itou.users.factories import (
    JobSeekerFactory,
    JobSeekerProfileFactory,
    JobSeekerProfileWithHexaAddressFactory,
    JobSeekerWithMockedAddressFactory,
    PrescriberFactory,
)


class JobApplicationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.JobApplication

    job_seeker = factory.SubFactory(JobSeekerFactory)
    to_siae = factory.SubFactory(SiaeFactory, with_membership=True)
    message = factory.Faker("sentence", nb_words=40)
    answer = factory.Faker("sentence", nb_words=40)
    hiring_start_at = timezone.localdate()
    hiring_end_at = timezone.localdate() + relativedelta(years=2)
    resume_link = "https://server.com/rockie-balboa.pdf"

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


class JobApplicationSentByJobSeekerFactory(JobApplicationFactory):
    """Generates a JobApplication() object sent by a job seeker."""

    sender = factory.SelfAttribute("job_seeker")
    sender_kind = SenderKind.JOB_SEEKER


class JobApplicationSentBySiaeFactory(JobApplicationFactory):
    """Generates a JobApplication() object sent by an Siae."""

    sender_kind = SenderKind.SIAE_STAFF
    # Currently an Siae can only postulate for itself,
    # this is the default behavior here.
    sender_siae = factory.LazyAttribute(lambda obj: obj.to_siae)
    sender = factory.LazyAttribute(lambda obj: obj.to_siae.members.first())


class JobApplicationSentByPrescriberFactory(JobApplicationFactory):
    """Generates a JobApplication() object sent by a prescriber."""

    sender = factory.SubFactory(PrescriberFactory)
    sender_kind = SenderKind.PRESCRIBER


class JobApplicationSentByPrescriberOrganizationFactory(JobApplicationSentByPrescriberFactory):
    """Generates a JobApplication() object sent by a prescriber member of an organization."""

    sender_prescriber_organization = factory.SubFactory(PrescriberOrganizationWithMembershipFactory)
    sender = factory.LazyAttribute(lambda obj: obj.sender_prescriber_organization.members.first())


class JobApplicationSentByAuthorizedPrescriberOrganizationFactory(JobApplicationSentByPrescriberFactory):
    """Generates a JobApplication() object sent by a prescriber member of an authorized organization."""

    sender_prescriber_organization = factory.SubFactory(PrescriberOrganizationWithMembershipFactory, authorized=True)
    sender = factory.LazyAttribute(lambda obj: obj.sender_prescriber_organization.members.first())


class JobApplicationSentByPrescriberPoleEmploiFactory(JobApplicationSentByPrescriberFactory):
    """Generates a JobApplication() object sent by a prescriber member of Pôle emploi organization."""

    sender_prescriber_organization = factory.SubFactory(PrescriberPoleEmploiWithMembershipFactory)
    sender = factory.LazyAttribute(lambda obj: obj.sender_prescriber_organization.members.first())


class JobApplicationWithEligibilityDiagnosis(JobApplicationSentByAuthorizedPrescriberOrganizationFactory):
    """Generates a JobApplication() object with an EligibilityDiagnosis() object."""

    eligibility_diagnosis = factory.SubFactory(
        EligibilityDiagnosisFactory,
        job_seeker=factory.SelfAttribute("..job_seeker"),
        author=factory.SelfAttribute("..sender"),
    )


class JobApplicationWithApprovalFactory(JobApplicationWithEligibilityDiagnosis):
    """Generates a JobApplication() object with an Approval() object."""

    state = models.JobApplicationWorkflow.STATE_ACCEPTED
    approval = factory.SubFactory(ApprovalFactory, user=factory.SelfAttribute("..job_seeker"))


class JobApplicationWithoutApprovalFactory(JobApplicationSentByPrescriberFactory):
    """Generates a JobApplication() object without an Approval() object."""

    state = models.JobApplicationWorkflow.STATE_ACCEPTED
    hiring_without_approval = True


class JobApplicationWithApprovalNotCancellableFactory(JobApplicationWithApprovalFactory):
    hiring_start_at = timezone.localdate() - relativedelta(days=5)
    hiring_end_at = timezone.localdate() + relativedelta(years=2, days=-5)


class JobApplicationWithJobSeekerProfileFactory(JobApplicationWithApprovalNotCancellableFactory):
    """
    This job application has a jobseeker with an EMPTY job seeker profile

    Suitable for employee records tests
    """

    @factory.post_generation
    def set_job_seeker_profile(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return
        JobSeekerProfileFactory(user=self.job_seeker).save()


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
        JobSeekerProfileWithHexaAddressFactory(user=self.job_seeker).save()
