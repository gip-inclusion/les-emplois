import string

import factory.fuzzy
from django.utils import timezone

from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation
from itou.siaes import models
from itou.users.factories import SiaeStaffFactory
from itou.utils.address.departments import DEPARTMENTS


NAF_CODES = ["9522Z", "7820Z", "6312Z", "8130Z", "1071A", "5510Z"]

NOW = timezone.now()
GRACE_PERIOD = timezone.timedelta(days=models.SiaeConvention.DEACTIVATION_GRACE_PERIOD_IN_DAYS)
ONE_DAY = timezone.timedelta(days=1)


class SiaeConventionFactory(factory.django.DjangoModelFactory):
    """Generate an SiaeConvention() object for unit tests."""

    class Meta:
        model = models.SiaeConvention

    # Don't start a SIRET with 0.
    siret_signature = factory.fuzzy.FuzzyText(length=13, chars=string.digits, prefix="1")
    kind = models.Siae.KIND_EI
    asp_id = factory.Sequence(int)
    is_active = True


class SiaeFactory(factory.django.DjangoModelFactory):
    """Generate an Siae() object for unit tests."""

    class Meta:
        model = models.Siae

    # Don't start a SIRET with 0.
    siret = factory.fuzzy.FuzzyText(length=13, chars=string.digits, prefix="1")
    naf = factory.fuzzy.FuzzyChoice(NAF_CODES)
    kind = models.Siae.KIND_EI
    name = factory.Faker("company", locale="fr_FR")
    phone = factory.fuzzy.FuzzyText(length=10, chars=string.digits)
    email = factory.Faker("email", locale="fr_FR")
    auth_email = factory.Faker("email", locale="fr_FR")
    department = factory.fuzzy.FuzzyChoice(DEPARTMENTS.keys())
    address_line_1 = factory.Faker("street_address", locale="fr_FR")
    post_code = factory.Faker("postalcode")
    city = factory.Faker("city", locale="fr_FR")
    source = models.Siae.SOURCE_ASP
    convention = factory.SubFactory(SiaeConventionFactory)


class SiaeMembershipFactory(factory.django.DjangoModelFactory):
    """
    Generate an SiaeMembership() object (with its related Siae() and User() objects) for unit tests.
    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    class Meta:
        model = models.SiaeMembership

    user = factory.SubFactory(SiaeStaffFactory)
    siae = factory.SubFactory(SiaeFactory)
    is_siae_admin = True


class SiaeWithMembershipFactory(SiaeFactory):
    """
    Generates an Siae() object with a member for unit tests.
    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    membership = factory.RelatedFactory(SiaeMembershipFactory, "siae")


class SiaeWith2MembershipsFactory(SiaeFactory):
    """
    Generates an Siae() object with 2 members for unit tests.
    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    membership1 = factory.RelatedFactory(SiaeMembershipFactory, "siae")
    membership2 = factory.RelatedFactory(SiaeMembershipFactory, "siae", is_siae_admin=False)


class SiaeWith4MembershipsFactory(SiaeFactory):
    """
    Generates an Siae() object with 4 members for unit tests.
    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    # active admin user
    membership1 = factory.RelatedFactory(SiaeMembershipFactory, "siae")
    # active normal user
    membership2 = factory.RelatedFactory(SiaeMembershipFactory, "siae", is_siae_admin=False)
    # inactive admin user
    membership3 = factory.RelatedFactory(SiaeMembershipFactory, "siae", user__is_active=False)
    # inactive normal user
    membership4 = factory.RelatedFactory(SiaeMembershipFactory, "siae", is_siae_admin=False, user__is_active=False)


class SiaeWithMembershipAndJobsFactory(SiaeWithMembershipFactory):
    """
    Generates an Siae() object with a member and random jobs (based on given ROME codes) for unit tests.
    https://factoryboy.readthedocs.io/en/latest/recipes.html#simple-many-to-many-relationship

    Usage:
        SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105", "N1103", "N4105"))
    """

    @factory.post_generation
    def romes(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return

        romes = extracted or ("N1101", "N1105", "N1103", "N4105")
        create_test_romes_and_appellations(romes)
        # Pick random results.
        appellations = Appellation.objects.order_by("?")[: len(romes)]
        self.jobs.add(*appellations)


class SiaeConventionPendingGracePeriodFactory(SiaeConventionFactory):
    """
    Generates a SiaeConvention() object which is inactive but still experiencing its grace period.
    """

    is_active = False
    deactivated_at = NOW - GRACE_PERIOD + ONE_DAY


class SiaePendingGracePeriodFactory(SiaeFactory):
    convention = factory.SubFactory(SiaeConventionPendingGracePeriodFactory)


class SiaeConventionAfterGracePeriodFactory(SiaeConventionFactory):
    """
    Generates an SiaeConvention() object which is inactive and has passed its grace period.
    """

    is_active = False
    deactivated_at = NOW - GRACE_PERIOD - ONE_DAY


class SiaeAfterGracePeriodFactory(SiaeFactory):
    convention = factory.SubFactory(SiaeConventionAfterGracePeriodFactory)
