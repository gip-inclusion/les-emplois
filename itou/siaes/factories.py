import string

from django.conf import settings

import factory
import factory.fuzzy

from itou.siaes import models
from itou.users.factories import SiaeStaffFactory


NAF_CODES = ["9522Z", "7820Z", "6312Z", "8130Z", "1071A", "5510Z"]


class SiaeFactory(factory.django.DjangoModelFactory):
    """Generates Siae() objects for unit tests."""

    class Meta:
        model = models.Siae

    siret = factory.fuzzy.FuzzyText(length=14, chars=string.digits)
    naf = factory.fuzzy.FuzzyChoice(NAF_CODES)
    name = factory.Sequence(lambda n: f"SIAE_{n}")
    phone = factory.fuzzy.FuzzyText(length=10, chars=string.digits)
    email = factory.LazyAttribute(lambda obj: f"{obj.name}@example.com")
    department = factory.fuzzy.FuzzyChoice(settings.ITOU_TEST_DEPARTMENTS)


class SiaeMembershipFactory(factory.django.DjangoModelFactory):
    """
    Generates SiaeMembership() objects (with related Siae() and User()) for unit tests.
    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    class Meta:
        model = models.SiaeMembership

    user = factory.SubFactory(SiaeStaffFactory)
    siae = factory.SubFactory(SiaeFactory)
    is_siae_admin = True
