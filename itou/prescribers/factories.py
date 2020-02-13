import string

import factory
import factory.fuzzy

from itou.prescribers import models
from itou.users.factories import PrescriberFactory


class PrescriberOrganizationFactory(factory.django.DjangoModelFactory):
    """Returns a PrescriberOrganization() object."""

    class Meta:
        model = models.PrescriberOrganization

    name = factory.Faker("name", locale="fr_FR")
    siret = factory.fuzzy.FuzzyText(length=14, chars=string.digits)
    phone = factory.fuzzy.FuzzyText(length=10, chars=string.digits)
    email = factory.Faker("email", locale="fr_FR")


class PrescriberMembershipFactory(factory.django.DjangoModelFactory):
    """
    Returns a PrescriberMembership() object with:
    - its related PrescriberOrganization()
    - its related User()

    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    class Meta:
        model = models.PrescriberMembership

    user = factory.SubFactory(PrescriberFactory)
    organization = factory.SubFactory(PrescriberOrganizationFactory)
    is_admin = True


class PrescriberOrganizationWithMembershipFactory(PrescriberOrganizationFactory):
    """
    Returns a PrescriberOrganization() object with a related PrescriberMembership() object.

    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    membership = factory.RelatedFactory(PrescriberMembershipFactory, "organization")


class AuthorizedPrescriberOrganizationWithMembershipFactory(
    PrescriberOrganizationWithMembershipFactory
):
    """
    Returns a PrescriberOrganization() object with a related authorized PrescriberMembership() object.

    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    is_authorized = True
