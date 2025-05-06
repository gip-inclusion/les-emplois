import datetime

import factory
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from faker import Faker

from itou.companies.enums import CompanyKind
from itou.eligibility import models
from itou.eligibility.enums import AuthorKind
from itou.eligibility.models.common import AbstractEligibilityDiagnosisModel
from itou.eligibility.models.geiq import GEIQAdministrativeCriteria
from itou.eligibility.models.iae import AdministrativeCriteria
from itou.users.enums import IdentityCertificationAuthorities
from itou.users.models import IdentityCertification
from tests.companies.factories import CompanyFactory, CompanyWith2MembershipsFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory


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
                lambda obj: faker.date_time(tzinfo=timezone.get_current_timezone(), end_datetime=obj.expires_at)
            ),
        )
        certifiable = factory.Trait(
            job_seeker__certifiable=True,
            from_employer=factory.Maybe(
                "from_prescriber",
                yes_declaration=None,
                no_declaration=True,
            ),
        )

    created_at = factory.LazyFunction(timezone.now)
    expires_at = factory.LazyAttribute(
        lambda obj: timezone.localdate(obj.created_at)
        + relativedelta(months=AbstractEligibilityDiagnosisModel.EXPIRATION_DELAY_MONTHS)
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
            author_siae=factory.SubFactory(CompanyFactory, subject_to_eligibility=True, with_membership=True),
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

    eligibility_diagnosis = factory.SubFactory(IAEEligibilityDiagnosisFactory, from_employer=True)
    administrative_criteria = factory.Iterator(models.AdministrativeCriteria.objects.certifiable())

    @factory.post_generation
    def identity_certification(obj, create, extracted, **kwargs):
        if obj.certified is not None:
            IdentityCertification.objects.create(
                certifier=IdentityCertificationAuthorities.API_PARTICULIER,
                jobseeker_profile=obj.eligibility_diagnosis.job_seeker.jobseeker_profile,
            )
