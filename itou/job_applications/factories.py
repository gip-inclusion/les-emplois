import factory
import factory.fuzzy

from itou.job_applications import models
from itou.prescribers.factories import PrescriberWithMembershipFactory
from itou.siaes.factories import SiaeWithMembershipFactory
from itou.users.factories import JobSeekerFactory


class JobApplicationFactory(factory.django.DjangoModelFactory):
    """Generates a JobApplication() object for unit tests."""

    class Meta:
        model = models.JobApplication

    job_seeker = factory.SubFactory(JobSeekerFactory)
    siae = factory.SubFactory(SiaeWithMembershipFactory)
    message = factory.Faker("sentence", nb_words=40)
    answer = factory.Faker("sentence", nb_words=40)

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


class JobApplicationWithPrescriberOrganizationFactory(JobApplicationFactory):
    """Generates a JobApplication() object with a PrescriberOrganization() and its user for unit tests."""

    prescriber = factory.SubFactory(PrescriberWithMembershipFactory)
    prescriber_user = factory.LazyAttribute(lambda o: o.prescriber.members.first())
