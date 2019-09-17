import string

import factory
import factory.fuzzy

from itou.prescribers import models
from itou.users.factories import PrescriberStaffFactory


class PrescriberOrganizationFactory(factory.django.DjangoModelFactory):
    """Generate a PrescriberOrganization() object for unit tests."""

    class Meta:
        model = models.PrescriberOrganization

    siret = factory.fuzzy.FuzzyText(length=14, chars=string.digits)
    name = factory.Sequence(lambda n: f"prescriber{n}")
    phone = factory.fuzzy.FuzzyText(length=10, chars=string.digits)
    email = factory.LazyAttribute(lambda obj: f"{obj.name}@example.com")


class PrescriberMembershipFactory(factory.django.DjangoModelFactory):
    """
    Generates:
    - a PrescriberMembership()
    - its related PrescriberOrganization()
    - its related User()

    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    class Meta:
        model = models.PrescriberMembership

    user = factory.SubFactory(PrescriberStaffFactory)
    organization = factory.SubFactory(PrescriberOrganizationFactory)
    is_admin = True


class PrescriberWithMembershipFactory(PrescriberOrganizationFactory):
    """
    Generates a PrescriberOrganization() object with a member for unit tests.

    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    membership = factory.RelatedFactory(PrescriberMembershipFactory, "organization")
