import random

import factory
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from itou.companies.enums import CompanyKind
from itou.eligibility import models
from itou.eligibility.enums import AuthorKind
from tests.companies.factories import CompanyFactory, CompanyWith2MembershipsFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory


class AbstractEligibilityDiagnosisModelFactory(factory.django.DjangoModelFactory):
    class Meta:
        abstract = True

    class Params:
        from_prescriber = factory.Trait(
            author_kind=AuthorKind.PRESCRIBER,
            author_prescriber_organization=factory.SubFactory(
                PrescriberOrganizationWithMembershipFactory, authorized=True
            ),
            author=factory.LazyAttribute(lambda obj: obj.author_prescriber_organization.members.first()),
        )
        expired = factory.Trait(
            expires_at=factory.LazyFunction(timezone.now),
            created_at=factory.LazyAttribute(lambda obj: obj.expires_at - relativedelta(months=6)),
        )

    created_at = factory.LazyFunction(timezone.now)
    job_seeker = factory.SubFactory(JobSeekerFactory)


class GEIQEligibilityDiagnosisFactory(AbstractEligibilityDiagnosisModelFactory):
    """Same as factories below, but :
    - with all possible author types
    - tailored for GEIQ tests."""

    class Meta:
        model = models.GEIQEligibilityDiagnosis

    class Params:
        from_geiq = factory.Trait(
            author_kind=AuthorKind.GEIQ,
            author_geiq=factory.SubFactory(CompanyWith2MembershipsFactory, kind=CompanyKind.GEIQ, with_jobs=True),
            author=factory.LazyAttribute(lambda obj: obj.author_geiq.members.first()),
        )


def _get_iae_administrative_criteria(self, create, extracted, **kwargs):
    if not create:
        # Simple build, do nothing.
        return

    # Pick random results.
    criteria = models.AdministrativeCriteria.objects.order_by("?")[: random.randint(2, 5)]
    self.administrative_criteria.add(*criteria)


def _get_iae_certifiable_criteria(self, create, extracted, **kwargs):
    if not create:
        # Simple build, do nothing.
        return

    # Pick random results.
    criteria = models.AdministrativeCriteria.objects.certifiable().order_by("?")[: random.randint(2, 5)]
    self.administrative_criteria.add(*criteria)


def _get_iae_not_certifiable_criteria(self, create, extracted, **kwargs):
    if not create:
        # Simple build, do nothing.
        return

    # Pick random results.
    criteria = models.AdministrativeCriteria.objects.not_certifiable().order_by("?")[: random.randint(2, 5)]
    self.administrative_criteria.add(*criteria)


class IAEEligibilityDiagnosisFactory(AbstractEligibilityDiagnosisModelFactory):
    """Generate an EligibilityDiagnosis() object whose author is an authorized prescriber organization."""

    class Meta:
        model = models.EligibilityDiagnosis
        skip_postgeneration_save = True

    class Params:
        from_employer = factory.Trait(
            author_kind=AuthorKind.EMPLOYER,
            author_siae=factory.SubFactory(CompanyFactory, subject_to_eligibility=True, with_membership=True),
            author=factory.LazyAttribute(lambda obj: obj.author_siae.members.first()),
        )
        # TODO(cms): maybe we should only select certifiable criteria, or not certifiable, to avoid flaky tests.
        with_criteria = factory.Trait(romes=factory.PostGeneration(_get_iae_administrative_criteria))
        with_certifiable_criteria = factory.Trait(romes=factory.PostGeneration(_get_iae_certifiable_criteria))
        with_not_certifiable_criteria = factory.Trait(romes=factory.PostGeneration(_get_iae_not_certifiable_criteria))
