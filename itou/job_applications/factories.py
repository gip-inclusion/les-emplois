import factory
import factory.fuzzy

from itou.job_applications import models
from itou.prescribers.factories import (
    AuthorizedPrescriberOrganizationWithMembershipFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from itou.siaes.factories import SiaeWithMembershipFactory
from itou.users.factories import PrescriberFactory, JobSeekerFactory


class JobApplicationFactory(factory.django.DjangoModelFactory):
    """Generates a JobApplication() object."""

    class Meta:
        model = models.JobApplication

    job_seeker = factory.SubFactory(JobSeekerFactory)
    to_siae = factory.SubFactory(SiaeWithMembershipFactory)
    message = factory.Faker("sentence", nb_words=40)
    # answer = factory.Faker("sentence", nb_words=40)

    @factory.post_generation
    def jobs(self, create, extracted, **kwargs):
        """
        Add jobs in which the job seeker is interested.
        https://factoryboy.readthedocs.io/en/latest/recipes.html#simple-many-to-many-relationship

        Usage:
            job1 = Appellation.objects.filter(code='10933')
            job2 = Appellation.objects.filter(code='10934')
            JobApplicationFactory(jobs=(job1, job2))
        """
        if not create:
            # Simple build, do nothing.
            return

        if extracted:
            # A list of jobs were passed in, use them.
            for job in extracted:
                self.jobs.add(job)


class JobApplicationSentByJobSeekerFactory(JobApplicationFactory):
    """Generates a JobApplication() object sent by a job seeker."""

    sender = factory.SelfAttribute("job_seeker")
    sender_kind = models.JobApplication.SENDER_KIND_JOB_SEEKER


class JobApplicationSentByPrescriberFactory(JobApplicationFactory):
    """Generates a JobApplication() object sent by a prescriber."""

    sender = factory.SubFactory(PrescriberFactory)
    sender_kind = models.JobApplication.SENDER_KIND_PRESCRIBER


class JobApplicationSentByPrescriberOrganizationFactory(JobApplicationFactory):
    """Generates a JobApplication() object sent by a prescriber member of an organization."""

    sender_kind = models.JobApplication.SENDER_KIND_PRESCRIBER
    sender_prescriber_organization = factory.SubFactory(
        PrescriberOrganizationWithMembershipFactory
    )

    @factory.post_generation
    def set_sender(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return
        self.sender = self.sender_prescriber_organization.members.first()
        self.save()


class JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
    JobApplicationFactory
):
    """Generates a JobApplication() object sent by a prescriber member of an authorized organization."""

    sender_kind = models.JobApplication.SENDER_KIND_PRESCRIBER
    sender_prescriber_organization = factory.SubFactory(
        AuthorizedPrescriberOrganizationWithMembershipFactory
    )

    @factory.post_generation
    def set_sender(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return
        self.sender = self.sender_prescriber_organization.members.first()
        self.save()
