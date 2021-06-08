import datetime

import factory
import factory.fuzzy
from dateutil.relativedelta import relativedelta

from itou.approvals.factories import ApprovalFactory
from itou.job_applications import models
from itou.jobs.models import Appellation
from itou.prescribers.factories import (
    AuthorizedPrescriberOrganizationWithMembershipFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from itou.siaes.factories import SiaeWithMembershipFactory
from itou.siaes.models import SiaeJobDescription
from itou.users.factories import (
    JobSeekerFactory,
    JobSeekerProfileFactory,
    JobSeekerWithMockedAddressFactory,
    PrescriberFactory,
)
from itou.users.models import User


class JobApplicationFactory(factory.django.DjangoModelFactory):
    """Generates a JobApplication() object."""

    class Meta:
        model = models.JobApplication

    job_seeker = factory.SubFactory(JobSeekerFactory)
    to_siae = factory.SubFactory(SiaeWithMembershipFactory)
    message = factory.Faker("sentence", nb_words=40)
    answer = factory.Faker("sentence", nb_words=40)
    hiring_start_at = datetime.date.today()
    hiring_end_at = datetime.date.today() + relativedelta(years=2)
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
                    siae_job_description = SiaeJobDescription.objects.create(
                        siae=self.to_siae, appellation=siae_job_description
                    )
                self.selected_jobs.add(siae_job_description)


class JobApplicationSentByJobSeekerFactory(JobApplicationFactory):
    """Generates a JobApplication() object sent by a job seeker."""

    sender = factory.SelfAttribute("job_seeker")
    sender_kind = models.JobApplication.SENDER_KIND_JOB_SEEKER


class JobApplicationSentBySiaeFactory(JobApplicationFactory):
    """Generates a JobApplication() object sent by an Siae."""

    sender_kind = models.JobApplication.SENDER_KIND_SIAE_STAFF
    # Currently an Siae can only postulate for itself,
    # this is the default behavior here.
    sender_siae = factory.LazyAttribute(lambda obj: obj.to_siae)


class JobApplicationSentByPrescriberFactory(JobApplicationFactory):
    """Generates a JobApplication() object sent by a prescriber."""

    sender = factory.SubFactory(PrescriberFactory)
    sender_kind = models.JobApplication.SENDER_KIND_PRESCRIBER


class JobApplicationSentByPrescriberOrganizationFactory(JobApplicationFactory):
    """Generates a JobApplication() object sent by a prescriber member of an organization."""

    sender_kind = models.JobApplication.SENDER_KIND_PRESCRIBER
    sender_prescriber_organization = factory.SubFactory(PrescriberOrganizationWithMembershipFactory)

    @factory.post_generation
    def set_sender(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return
        self.sender = self.sender_prescriber_organization.members.first()
        self.save()


class JobApplicationSentByAuthorizedPrescriberOrganizationFactory(JobApplicationFactory):
    """Generates a JobApplication() object sent by a prescriber member of an authorized organization."""

    sender_kind = models.JobApplication.SENDER_KIND_PRESCRIBER
    sender_prescriber_organization = factory.SubFactory(AuthorizedPrescriberOrganizationWithMembershipFactory)

    @factory.post_generation
    def set_sender(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return
        self.sender = self.sender_prescriber_organization.members.first()
        self.save()


class JobApplicationWithApprovalFactory(JobApplicationSentByPrescriberFactory):
    """
    Generates a Job Application and an Approval.
    """

    approval = factory.SubFactory(ApprovalFactory)
    state = models.JobApplicationWorkflow.STATE_ACCEPTED

    @factory.post_generation
    def set_approval_user(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return
        self.approval.user = self.job_seeker
        self.approval.save()


class JobApplicationWithoutApprovalFactory(JobApplicationSentByPrescriberFactory):
    """
    Generates a Job Application without Approval.
    """

    state = models.JobApplicationWorkflow.STATE_ACCEPTED
    hiring_without_approval = True


class JobApplicationWithApprovalNotCancellableFactory(JobApplicationWithApprovalFactory):
    hiring_start_at = datetime.date.today() - relativedelta(days=5)
    hiring_end_at = datetime.date.today() + relativedelta(years=2, days=-5)


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

    @factory.post_generation
    def set_job_seeker_profile(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return
        self.job_seeker.title = User.Title.M

        JobSeekerProfileFactory(user=self.job_seeker).save()
