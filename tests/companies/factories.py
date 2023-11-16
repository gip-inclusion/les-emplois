import functools
import random
import string

import factory.fuzzy
from django.utils import timezone

from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENTS, department_from_postcode
from itou.companies import models
from itou.companies.enums import SIAE_WITH_CONVENTION_KINDS, CompanyKind, ContractType
from itou.jobs.models import Appellation
from tests.jobs.factories import create_test_romes_and_appellations
from tests.users.factories import EmployerFactory


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
    start_at = factory.LazyFunction(lambda: timezone.now() - ONE_MONTH)
    end_at = factory.LazyFunction(lambda: timezone.now() + ONE_MONTH)


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


def _create_fake_postcode():
    postcode = random.choice(list(DEPARTMENTS))
    # add 3 numbers
    postcode += f"{int(random.randint(0, 999)):03}"
    # trunc to keep only 5 numbers, in case the department was 3 number long
    return postcode[:5]


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
            kind=factory.fuzzy.FuzzyChoice(SIAE_WITH_CONVENTION_KINDS),
        )
        not_subject_to_eligibility = factory.Trait(
            kind=factory.fuzzy.FuzzyChoice([kind for kind in CompanyKind if kind not in SIAE_WITH_CONVENTION_KINDS]),
        )
        use_employee_record = factory.Trait(kind=factory.fuzzy.FuzzyChoice(models.Company.ASP_EMPLOYEE_RECORD_KINDS))
        with_membership = factory.Trait(
            membership=factory.RelatedFactory("tests.companies.factories.CompanyMembershipFactory", "company"),
        )
        with_jobs = factory.Trait(romes=factory.PostGeneration(_create_job_from_rome_code))
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
    post_code = factory.LazyFunction(_create_fake_postcode)
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


CompanyWithMembershipAndJobsFactory = functools.partial(CompanyFactory, with_membership=True, with_jobs=True)


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

    appellation = factory.LazyAttribute(lambda obj: Appellation.objects.order_by("?").first())
    company = factory.SubFactory(CompanyFactory)
    description = factory.Faker("sentence", locale="fr_FR")
    contract_type = factory.fuzzy.FuzzyChoice(ContractType.values)
    location = factory.LazyAttribute(lambda obj: City.objects.order_by("?").first())
    profile_description = factory.Faker("sentence", locale="fr_FR")
    market_context_description = factory.Faker("sentence", locale="fr_FR")
