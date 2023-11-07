import factory
from django.utils import timezone

from itou.companies.enums import CompanyKind
from itou.eligibility import models
from itou.eligibility.enums import AuthorKind
from tests.companies.factories import CompanyFactory, CompanyWith2MembershipsFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory


class GEIQEligibilityDiagnosisFactory(factory.django.DjangoModelFactory):
    """Same as factories below, but :
    - with all possible author types
    - tailored for GEIQ tests."""

    class Meta:
        model = models.GEIQEligibilityDiagnosis

    class Params:
        with_geiq = factory.Trait(
            author_kind=AuthorKind.GEIQ,
            author_geiq=factory.SubFactory(CompanyWith2MembershipsFactory, kind=CompanyKind.GEIQ, with_jobs=True),
            author=factory.LazyAttribute(lambda obj: obj.author_geiq.members.first()),
        )
        with_prescriber = factory.Trait(
            author_kind=AuthorKind.PRESCRIBER,
            author_prescriber_organization=factory.SubFactory(
                PrescriberOrganizationWithMembershipFactory, authorized=True
            ),
            author=factory.LazyAttribute(lambda obj: obj.author_prescriber_organization.members.first()),
        )
        expired = factory.Trait(expires_at=factory.LazyFunction(timezone.now))

    created_at = factory.LazyFunction(timezone.now)
    job_seeker = factory.SubFactory(JobSeekerFactory)


class EligibilityDiagnosisFactory(factory.django.DjangoModelFactory):
    """Generate an EligibilityDiagnosis() object whose author is an authorized prescriber organization."""

    class Meta:
        model = models.EligibilityDiagnosis

    created_at = factory.LazyFunction(timezone.now)
    author = factory.LazyAttribute(lambda obj: obj.author_prescriber_organization.members.first())
    author_kind = AuthorKind.PRESCRIBER
    author_prescriber_organization = factory.SubFactory(PrescriberOrganizationWithMembershipFactory, authorized=True)
    job_seeker = factory.SubFactory(JobSeekerFactory)


class EligibilityDiagnosisMadeBySiaeFactory(factory.django.DjangoModelFactory):
    """Generate an EligibilityDiagnosis() object whose author is an SIAE."""

    class Meta:
        model = models.EligibilityDiagnosis

    created_at = factory.LazyFunction(timezone.now)
    author = factory.LazyAttribute(lambda obj: obj.author_siae.members.first())
    author_kind = AuthorKind.EMPLOYER
    author_siae = factory.SubFactory(CompanyFactory, with_membership=True)
    job_seeker = factory.SubFactory(JobSeekerFactory)


class ExpiredEligibilityDiagnosisFactory(EligibilityDiagnosisFactory):
    expires_at = factory.SelfAttribute("created_at")


class ExpiredEligibilityDiagnosisMadeBySiaeFactory(EligibilityDiagnosisMadeBySiaeFactory):
    expires_at = factory.SelfAttribute("created_at")


class AdministrativeCriteriaFactory(factory.django.DjangoModelFactory):
    """
    The AdministrativeCriteria table is automatically populated with a fixture
    after a `post_migrate` signal at the start of the `eligibility` app.
    """

    class Meta:
        model = models.AdministrativeCriteria
