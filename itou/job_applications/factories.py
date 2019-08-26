import factory
import factory.fuzzy

from itou.job_applications import models
from itou.users.factories import JobSeekerFactory
from itou.siaes.factories import SiaeWithMembershipFactory


class JobRequestFactory(factory.django.DjangoModelFactory):
    """Generates JobRequest() objects for unit tests."""

    class Meta:
        model = models.JobRequest

    job_seeker = factory.SubFactory(JobSeekerFactory)
    siae = factory.SubFactory(SiaeWithMembershipFactory)
    motivation_message = factory.Faker("sentence", nb_words=40)

    # prescriber_user
    # prescriber

    @factory.post_generation
    def jobs(self, create, extracted, **kwargs):
        """
        Add jobs in which the job seeker is interested.
        https://factoryboy.readthedocs.io/en/latest/recipes.html#simple-many-to-many-relationship

        Usage:
            job1 = Appellation.objects.filter(code='10933')
            job2 = Appellation.objects.filter(code='10934')
            JobRequestFactory(jobs=(job1, job2))
        """
        if not create:
            # Simple build, do nothing.
            return

        if extracted:
            # A list of jobs were passed in, use them.
            for job in extracted:
                self.jobs.add(job)
