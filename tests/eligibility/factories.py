import datetime
import random

import factory
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from faker import Faker

from itou.companies.enums import CompanyKind
from itou.eligibility import models
from itou.eligibility.enums import AdministrativeCriteriaAnnex, AuthorKind
from itou.eligibility.models.common import AbstractEligibilityDiagnosisModel
from tests.companies.factories import CompanyFactory, CompanyWith2MembershipsFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory


def _add_administrative_criteria(self, create, extracted, qs, **kwargs):
    # Pick random results.
    criteria = qs.order_by("?")[: random.randint(2, 5)]
    self.administrative_criteria.add(*criteria)


faker = Faker()


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
            expires_at=factory.LazyFunction(lambda: timezone.localdate() - datetime.timedelta(days=1)),
            created_at=factory.LazyAttribute(
                lambda obj: timezone.make_aware(faker.date_time(end_datetime=obj.expires_at))
            ),
        )

    created_at = factory.LazyFunction(timezone.now)
    expires_at = factory.LazyAttribute(
        lambda obj: timezone.localdate(obj.created_at)
        + relativedelta(months=AbstractEligibilityDiagnosisModel.EXPIRATION_DELAY_MONTHS)
    )
    job_seeker = factory.SubFactory(JobSeekerFactory)


def _get_geiq_certifiable_criteria(self, create, extracted, **kwargs):
    qs = models.GEIQAdministrativeCriteria.objects.exclude(annex=AdministrativeCriteriaAnnex.NO_ANNEX).certifiable()
    _add_administrative_criteria(self, create, extracted, qs, **kwargs)


def _get_geiq_not_certifiable_criteria(self, create, extracted, **kwargs):
    qs = models.GEIQAdministrativeCriteria.objects.exclude(
        annex=AdministrativeCriteriaAnnex.NO_ANNEX
    ).not_certifiable()
    _add_administrative_criteria(self, create, extracted, qs, **kwargs)


class GEIQEligibilityDiagnosisFactory(AbstractEligibilityDiagnosisModelFactory):
    """Same as factories below, but :
    - with all possible author types
    - tailored for GEIQ tests."""

    class Meta:
        model = models.GEIQEligibilityDiagnosis
        skip_postgeneration_save = True

    class Params:
        from_geiq = factory.Trait(
            author_kind=AuthorKind.GEIQ,
            author_geiq=factory.SubFactory(CompanyWith2MembershipsFactory, kind=CompanyKind.GEIQ, with_jobs=True),
            author=factory.LazyAttribute(lambda obj: obj.author_geiq.members.first()),
        )
        with_certifiable_criteria = factory.Trait(romes=factory.PostGeneration(_get_geiq_certifiable_criteria))
        with_not_certifiable_criteria = factory.Trait(romes=factory.PostGeneration(_get_geiq_not_certifiable_criteria))


def _get_iae_certifiable_criteria(self, create, extracted, **kwargs):
    qs = models.AdministrativeCriteria.objects.certifiable()
    _add_administrative_criteria(self, create, extracted, qs, **kwargs)


def _get_iae_not_certifiable_criteria(self, create, extracted, **kwargs):
    qs = models.AdministrativeCriteria.objects.not_certifiable()
    _add_administrative_criteria(self, create, extracted, qs, **kwargs)


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
        with_certifiable_criteria = factory.Trait(romes=factory.PostGeneration(_get_iae_certifiable_criteria))
        with_not_certifiable_criteria = factory.Trait(romes=factory.PostGeneration(_get_iae_not_certifiable_criteria))
