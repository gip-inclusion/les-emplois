import string

import factory
import factory.fuzzy
from django.conf import settings

from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation
from itou.siaes import models
from itou.users.factories import SiaeStaffFactory


NAF_CODES = ["9522Z", "7820Z", "6312Z", "8130Z", "1071A", "5510Z"]


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
    department = factory.fuzzy.FuzzyChoice(settings.ITOU_TEST_DEPARTMENTS)
    address_line_1 = factory.Faker("street_address", locale="fr_FR")
    post_code = factory.Faker("postalcode")
    city = factory.Faker("city", locale="fr_FR")


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
        # Pick 4 random results.
        appellations = Appellation.objects.order_by("?")[:4]
        self.jobs.add(*appellations)
