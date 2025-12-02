import datetime
import random

import factory
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from faker import Faker

from itou.companies.enums import CompanyKind
from itou.eligibility import models
from itou.eligibility.enums import AdministrativeCriteriaKind, AuthorKind
from itou.eligibility.models.common import AbstractEligibilityDiagnosisModel
from itou.eligibility.models.geiq import GEIQAdministrativeCriteria
from itou.eligibility.models.iae import AdministrativeCriteria
from itou.users.enums import IdentityCertificationAuthorities
from itou.users.models import IdentityCertification
from itou.utils.types import InclusiveDateRange
from tests.companies.factories import CompanyFactory, CompanyWith2MembershipsFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.factory_boy import AutoNowOverrideMixin


faker = Faker()


class AbstractEligibilityDiagnosisModelFactory(AutoNowOverrideMixin, factory.django.DjangoModelFactory):
    class Meta:
        abstract = True

    class Params:
        from_prescriber = factory.Trait(
            author_kind=AuthorKind.PRESCRIBER,
            author_prescriber_organization=factory.SubFactory(
                PrescriberOrganizationFactory, authorized=True, with_membership=True
            ),
            author=factory.LazyAttribute(lambda obj: obj.author_prescriber_organization.members.first()),
        )
        expired = factory.Trait(
            expires_at=factory.LazyFunction(lambda: timezone.localdate() - datetime.timedelta(days=1)),
            created_at=factory.LazyAttribute(
                lambda obj: faker.date_time(tzinfo=timezone.get_current_timezone(), end_datetime=obj.expires_at)
            ),
        )
        certifiable = factory.Trait(
            # A birth_place is required. It could either be using
            # born_in_france or born_outside_france. The latter means less SQL queries.
            job_seeker__born_outside_france=True,
            from_employer=factory.Maybe(
                "from_prescriber",
                yes_declaration=None,
                no_declaration=True,
            ),
        )

    created_at = factory.LazyFunction(timezone.now)
    expires_at = factory.LazyAttribute(
        lambda obj: (
            timezone.localdate(obj.created_at)
            + relativedelta(months=AbstractEligibilityDiagnosisModel.EXPIRATION_DELAY_MONTHS)
        )
    )
    job_seeker = factory.SubFactory(JobSeekerFactory)


class GEIQEligibilityDiagnosisFactory(AbstractEligibilityDiagnosisModelFactory):
    """Same as factories below, but :
    - with all possible author types
    - tailored for GEIQ tests."""

    class Meta:
        model = models.GEIQEligibilityDiagnosis
        skip_postgeneration_save = True

    class Params:
        from_employer = factory.Trait(
            author_kind=AuthorKind.GEIQ,
            author_geiq=factory.SubFactory(CompanyWith2MembershipsFactory, kind=CompanyKind.GEIQ, with_jobs=True),
            author=factory.LazyAttribute(lambda obj: obj.author_geiq.members.first()),
        )

    @factory.post_generation
    def criteria_kinds(self, create, extracted, **kwargs):
        if create and extracted:
            admin_criterion = GEIQAdministrativeCriteria.objects.filter(kind__in=extracted)
            self.administrative_criteria.add(*admin_criterion)


class IAEEligibilityDiagnosisFactory(AbstractEligibilityDiagnosisModelFactory):
    """Generate an EligibilityDiagnosis() object whose author is an authorized prescriber organization."""

    class Meta:
        model = models.EligibilityDiagnosis
        skip_postgeneration_save = True

    class Params:
        from_employer = factory.Trait(
            author_kind=AuthorKind.EMPLOYER,
            author_siae=factory.SubFactory(CompanyFactory, subject_to_iae_rules=True, with_membership=True),
            author=factory.LazyAttribute(lambda obj: obj.author_siae.members.first()),
        )

    @factory.post_generation
    def criteria_kinds(self, create, extracted, **kwargs):
        if create and extracted:
            admin_criterion = AdministrativeCriteria.objects.filter(kind__in=extracted)
            self.administrative_criteria.add(*admin_criterion)


class IAESelectedAdministrativeCriteriaFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.SelectedAdministrativeCriteria
        skip_postgeneration_save = True

    class Params:
        criteria_certified = factory.Trait(
            certified_at=factory.SelfAttribute(".eligibility_diagnosis.created_at"),
            certification_period=factory.LazyAttribute(
                lambda obj: InclusiveDateRange(
                    timezone.localdate(obj.eligibility_diagnosis.created_at),
                    obj.eligibility_diagnosis.expires_at,
                )
            ),
        )
        criteria_not_certified = factory.Trait(
            certified_at=factory.SelfAttribute(".eligibility_diagnosis.created_at"),
            certification_period=InclusiveDateRange(empty=True),
        )
        criteria_certification_error = factory.Trait(
            certified_at=factory.SelfAttribute(".eligibility_diagnosis.created_at"),
            certification_period=None,
        )
        certifiable_by_api_particulier = factory.Trait(
            administrative_criteria=factory.LazyFunction(
                lambda: AdministrativeCriteria.objects.get(
                    kind=random.choice(list(AdministrativeCriteriaKind.certifiable_by_api_particulier()))
                )
            )
        )

    eligibility_diagnosis = factory.SubFactory(IAEEligibilityDiagnosisFactory, from_employer=True)
    administrative_criteria = factory.Iterator(models.AdministrativeCriteria.objects.certifiable())

    @factory.post_generation
    def identity_certification(obj, create, extracted, **kwargs):
        if obj.certification_period is not None:
            IdentityCertification.objects.create(
                certifier=IdentityCertificationAuthorities.API_PARTICULIER,
                jobseeker_profile=obj.eligibility_diagnosis.job_seeker.jobseeker_profile,
            )
