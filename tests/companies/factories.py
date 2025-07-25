import datetime
import functools
import string

import factory.fuzzy
from django.conf import settings
from django.utils import timezone

from itou.cities.models import City
from itou.common_apps.address.departments import department_from_postcode
from itou.companies import models
from itou.companies.enums import CompanyKind, ContractType
from itou.jobs.models import Appellation
from tests.cities.factories import create_city_vannes
from tests.jobs.factories import create_test_romes_and_appellations
from tests.users.factories import EmployerFactory
from tests.utils.test import create_fake_postcode


NAF_CODES = ["9522Z", "7820Z", "6312Z", "8130Z", "1071A", "5510Z"]

GRACE_PERIOD = timezone.timedelta(days=models.SiaeConvention.DEACTIVATION_GRACE_PERIOD_IN_DAYS)
ONE_DAY = timezone.timedelta(days=1)
ONE_MONTH = timezone.timedelta(days=30)


class SiaeFinancialAnnexFactory(factory.django.DjangoModelFactory):
    """Generate an SiaeFinancialAnnex() object for unit tests."""

    class Meta:
        model = models.SiaeFinancialAnnex

    # e.g. EI59V182019A1M1
    number = factory.Sequence(lambda n: f"EI59V{n:06d}A1M1")
    state = models.SiaeFinancialAnnex.STATE_VALID
    start_at = factory.LazyFunction(lambda: timezone.localdate() - ONE_MONTH)
    end_at = factory.LazyFunction(lambda: timezone.localdate() + ONE_MONTH)


class SiaeConventionFactory(factory.django.DjangoModelFactory):
    """Generate an SiaeConvention() object for unit tests."""

    class Meta:
        model = models.SiaeConvention
        django_get_or_create = ("asp_id", "kind")
        skip_postgeneration_save = True

    # Don't start a SIRET with 0.
    siret_signature = factory.fuzzy.FuzzyText(length=13, chars=string.digits, prefix="1")
    # FIXME(vperron): this should be made random
    kind = CompanyKind.EI
    # factory.Sequence() start with 0 and an ASP ID should be greater than 0
    asp_id = factory.Sequence(lambda n: n + 1)
    is_active = True
    financial_annex = factory.RelatedFactory(SiaeFinancialAnnexFactory, "convention")


def _create_job_from_rome_code(self, create, extracted, **kwargs):
    if not create:
        # Simple build, do nothing.
        return

    romes = extracted or ("N1101", "N1105", "N1103", "N4105")
    create_test_romes_and_appellations(romes)
    # Pick random results.
    appellations = Appellation.objects.order_by("?")[: len(romes)]
    self.jobs.add(*appellations)


class CompanyFactory(factory.django.DjangoModelFactory):
    """Generate a Company() object for unit tests.

    Usage:
        CompanyFactory(subject_to_eligibility=True, ...)
        CompanyFactory(not_subject_to_eligibility=True, ...)
        CompanyFactory(with_membership=True, ...)
        CompanyFactory(with_jobs=True, romes=("N1101", "N1105", "N1103", "N4105"), ...)
    """

    class Meta:
        model = models.Company
        skip_postgeneration_save = True

    class Params:
        subject_to_eligibility = factory.Trait(
            kind=factory.fuzzy.FuzzyChoice(CompanyKind.siae_kinds()),
        )
        not_subject_to_eligibility = factory.Trait(
            kind=factory.fuzzy.FuzzyChoice([kind for kind in CompanyKind if kind not in CompanyKind.siae_kinds()]),
        )
        use_employee_record = factory.Trait(kind=factory.fuzzy.FuzzyChoice(models.Company.ASP_EMPLOYEE_RECORD_KINDS))
        with_membership = factory.Trait(
            membership=factory.RelatedFactory("tests.companies.factories.CompanyMembershipFactory", "company"),
        )
        with_jobs = factory.Trait(romes=factory.PostGeneration(_create_job_from_rome_code))
        with_geocoding = factory.Trait(
            coords=factory.Faker("geopoint"),
            geocoding_score=factory.fuzzy.FuzzyFloat(0.0, 1.0, precision=3),
        )
        with_informations = factory.Trait(
            with_geocoding=True,
            brand=factory.Faker("company", locale="fr_FR"),
            description=factory.Faker("paragraph", locale="fr_FR"),
        )
        not_in_territorial_experimentation = factory.Trait(
            post_code=factory.LazyFunction(
                functools.partial(
                    create_fake_postcode,
                    ignore=[
                        *settings.GPS_NAV_ENTRY_DEPARTMENTS,
                        *settings.MON_RECAP_BANNER_DEPARTMENTS,
                    ],
                )
            )
        )
        for_snapshot = factory.Trait(
            name="ACME Inc.",
            address_line_1="112 rue de la Croix-Nivert",
            post_code="75015",
            city="Paris",
            membership=factory.Maybe(
                "with_membership",
                yes_declaration=factory.RelatedFactory(
                    "tests.companies.factories.CompanyMembershipFactory",
                    "company",
                    user__for_snapshot=True,
                ),
            ),
            email="contact@acmeinc.com",
            phone="0612345678",
            siret="012345678910",
        )

    # Don't start a SIRET with 0.
    siret = factory.fuzzy.FuzzyText(length=13, chars=string.digits, prefix="1")
    naf = factory.fuzzy.FuzzyChoice(NAF_CODES)
    # FIXME(vperron): this should be made random
    kind = CompanyKind.EI
    name = factory.Faker("company", locale="fr_FR")
    phone = factory.fuzzy.FuzzyText(length=10, chars=string.digits)
    email = factory.Faker("email", locale="fr_FR")
    auth_email = factory.Faker("email", locale="fr_FR")
    address_line_1 = factory.Faker("street_address", locale="fr_FR")
    post_code = factory.LazyFunction(create_fake_postcode)
    city = factory.Faker("city", locale="fr_FR")
    source = models.Company.SOURCE_ASP
    convention = factory.SubFactory(SiaeConventionFactory, kind=factory.SelfAttribute("..kind"))
    department = factory.LazyAttribute(lambda o: department_from_postcode(o.post_code))


class CompanyMembershipFactory(factory.django.DjangoModelFactory):
    """
    Generate a CompanyMembership() object (with its related Company() and User() objects) for unit tests.
    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    class Meta:
        model = models.CompanyMembership

    user = factory.SubFactory(EmployerFactory)
    company = factory.SubFactory(CompanyFactory)
    is_admin = True


class CompanyWith2MembershipsFactory(CompanyFactory):
    """
    Generates a Company() object with 2 members for unit tests.
    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    membership1 = factory.RelatedFactory(CompanyMembershipFactory, "company")
    membership2 = factory.RelatedFactory(CompanyMembershipFactory, "company", is_admin=False)


class CompanyWith4MembershipsFactory(CompanyFactory):
    """
    Generates a Company() object with 4 members for unit tests.
    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    # active admin user
    membership1 = factory.RelatedFactory(CompanyMembershipFactory, "company")
    # active normal user
    membership2 = factory.RelatedFactory(CompanyMembershipFactory, "company", is_admin=False)
    # inactive admin user
    membership3 = factory.RelatedFactory(CompanyMembershipFactory, "company", user__is_active=False)
    # inactive normal user
    membership4 = factory.RelatedFactory(CompanyMembershipFactory, "company", is_admin=False, user__is_active=False)


class CompanyWithMembershipAndJobsFactory(CompanyFactory):
    with_membership = True
    with_jobs = True


class SiaeConventionPendingGracePeriodFactory(SiaeConventionFactory):
    """
    Generates a SiaeConvention() object which is inactive but still experiencing its grace period.
    """

    is_active = False
    deactivated_at = factory.LazyFunction(lambda: timezone.now() - GRACE_PERIOD + ONE_DAY)


class CompanyPendingGracePeriodFactory(CompanyFactory):
    convention = factory.SubFactory(SiaeConventionPendingGracePeriodFactory)


class SiaeConventionAfterGracePeriodFactory(SiaeConventionFactory):
    """
    Generates an SiaeConvention() object which is inactive and has passed its grace period.
    """

    is_active = False
    deactivated_at = factory.LazyFunction(lambda: timezone.now() - GRACE_PERIOD - ONE_DAY)


class CompanyAfterGracePeriodFactory(CompanyFactory):
    convention = factory.SubFactory(SiaeConventionAfterGracePeriodFactory)


class JobDescriptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.JobDescription

    class Params:
        for_snapshot = factory.Trait(
            appellation=factory.LazyAttribute(lambda obj: Appellation.objects.order_by("pk").first()),
            description="Une description statique",
            contract_type=ContractType.PERMANENT,
            location=factory.LazyAttribute(lambda obj: create_city_vannes()),
            profile_description="Un profil statique",
            market_context_description="Un contexte de marché stable",
            company__for_snapshot=True,
        )

    appellation = factory.LazyAttribute(lambda obj: Appellation.objects.order_by("?").first())
    company = factory.SubFactory(CompanyFactory)
    description = factory.Faker("sentence", locale="fr_FR")
    contract_type = factory.fuzzy.FuzzyChoice(ContractType.values)
    location = factory.LazyAttribute(lambda obj: City.objects.order_by("?").first())
    profile_description = factory.Faker("sentence", locale="fr_FR")
    market_context_description = factory.Faker("sentence", locale="fr_FR")
    last_employer_update_at = factory.Faker(
        "date_time_between", start_date="-30d", end_date="-3d", tzinfo=datetime.UTC
    )
