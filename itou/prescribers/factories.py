import string

import factory
import factory.fuzzy

from itou.prescribers import models
from itou.users.factories import PrescriberStaffFactory


class PrescriberFactory(factory.django.DjangoModelFactory):
    """Generate an Prescriber() object for unit tests."""

    class Meta:
        model = models.Prescriber

    siret = factory.fuzzy.FuzzyText(length=14, chars=string.digits)
    name = factory.Sequence(lambda n: f"prescriber{n}")
    phone = factory.fuzzy.FuzzyText(length=10, chars=string.digits)
    email = factory.LazyAttribute(lambda obj: f"{obj.name}@example.com")


class PrescriberMembershipFactory(factory.django.DjangoModelFactory):
    """
    Generate an PrescriberMembership() object (with its related Prescriber() and User() objects) for unit tests.
    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    class Meta:
        model = models.PrescriberMembership

    user = factory.SubFactory(PrescriberStaffFactory)
    prescriber = factory.SubFactory(PrescriberFactory)
    is_prescriber_admin = True


class PrescriberWithMembershipFactory(PrescriberFactory):
    """
    Generates an Prescriber() object with a member for unit tests.
    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    membership = factory.RelatedFactory(PrescriberMembershipFactory, "prescriber")
