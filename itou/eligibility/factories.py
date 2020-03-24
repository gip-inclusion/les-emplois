import factory

from itou.eligibility import models
from itou.users.factories import JobSeekerFactory, PrescriberFactory


class EligibilityDiagnosisFactory(factory.django.DjangoModelFactory):
    """Generate an EligibilityDiagnosis() object for unit tests."""

    class Meta:
        model = models.EligibilityDiagnosis

    job_seeker = factory.SubFactory(JobSeekerFactory)
    author = factory.SubFactory(PrescriberFactory)
    author_kind = models.EligibilityDiagnosis.AUTHOR_KIND_PRESCRIBER


class AdministrativeCriteriaFactory(factory.django.DjangoModelFactory):
    """
    The AdministrativeCriteria table is automatically populated with a fixture at the end of
    eligibility's migration #0003.
    """

    pass
