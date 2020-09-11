import factory
from django.utils import timezone

from itou.eligibility import models
from itou.prescribers.factories import AuthorizedPrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeWithMembershipFactory
from itou.users.factories import JobSeekerFactory


class EligibilityDiagnosisFactory(factory.django.DjangoModelFactory):
    """Generate an EligibilityDiagnosis() object whose author is an authorized prescriber organization."""

    class Meta:
        model = models.EligibilityDiagnosis

    author = factory.LazyAttribute(lambda obj: obj.author_prescriber_organization.members.first())
    author_kind = models.EligibilityDiagnosis.AUTHOR_KIND_PRESCRIBER
    author_prescriber_organization = factory.SubFactory(AuthorizedPrescriberOrganizationWithMembershipFactory)
    job_seeker = factory.SubFactory(JobSeekerFactory)


class EligibilityDiagnosisMadeBySiaeFactory(factory.django.DjangoModelFactory):
    """Generate an EligibilityDiagnosis() object whose author is an SIAE."""

    class Meta:
        model = models.EligibilityDiagnosis

    author = factory.LazyAttribute(lambda obj: obj.author_siae.members.first())
    author_kind = models.EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF
    author_siae = factory.SubFactory(SiaeWithMembershipFactory)
    job_seeker = factory.SubFactory(JobSeekerFactory)


class ExpiredEligibilityDiagnosisFactory(EligibilityDiagnosisFactory):

    created_at = factory.LazyAttribute(
        lambda self: models.EligibilityDiagnosis.get_expiration_dt() - timezone.timedelta(days=1)
    )


class AdministrativeCriteriaFactory(factory.django.DjangoModelFactory):
    """
    The AdministrativeCriteria table is automatically populated with a fixture at the end of
    eligibility's migration #0003.
    """

    pass
