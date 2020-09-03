import factory
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from itou.eligibility import models
from itou.siaes.factories import SiaeFactory
from itou.users.factories import JobSeekerFactory, PrescriberFactory, SiaeStaffFactory


class EligibilityDiagnosisFactory(factory.django.DjangoModelFactory):
    """Generate an EligibilityDiagnosis() object for unit tests."""

    class Meta:
        model = models.EligibilityDiagnosis

    job_seeker = factory.SubFactory(JobSeekerFactory)


class PrescriberEligibilityDiagnosisFactory(EligibilityDiagnosisFactory):
    author = factory.SubFactory(PrescriberFactory)
    author_kind = models.EligibilityDiagnosis.AUTHOR_KIND_PRESCRIBER


class SiaeEligibilityDiagnosisFactory(EligibilityDiagnosisFactory):
    author = factory.SubFactory(SiaeStaffFactory)
    author_kind = models.EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF
    author_siae = factory.SubFactory(SiaeFactory)


class ExpiredPrescriberEligibilityDiagnosisFactory(PrescriberEligibilityDiagnosisFactory):
    created_at = factory.LazyAttribute(
        lambda self: timezone.now() - relativedelta(months=models.EligibilityDiagnosis.EXPIRATION_DELAY_MONTHS, days=1)
    )


class ExpiredSiaeEligibilityDiagnosisFactory(SiaeEligibilityDiagnosisFactory):
    created_at = factory.LazyAttribute(
        lambda self: timezone.now() - relativedelta(months=models.EligibilityDiagnosis.EXPIRATION_DELAY_MONTHS, days=1)
    )


class AdministrativeCriteriaFactory(factory.django.DjangoModelFactory):
    """
    The AdministrativeCriteria table is automatically populated with a fixture at the end of
    eligibility's migration #0003.
    """

    pass
