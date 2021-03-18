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
    # Don't start a SIRET with 0.
    siret = factory.fuzzy.FuzzyText(length=13, chars=string.digits, prefix="1")
    phone = factory.fuzzy.FuzzyText(length=10, chars=string.digits)
    email = factory.Faker("email", locale="fr_FR")
    kind = models.PrescriberOrganization.Kind.PE


class AuthorizedPrescriberOrganizationFactory(PrescriberOrganizationFactory):
    """Returns an authorized PrescriberOrganization() object."""

    is_authorized = True
    authorization_status = models.PrescriberOrganization.AuthorizationStatus.VALIDATED


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
    is_active = True


class PrescriberOrganizationWithMembershipFactory(PrescriberOrganizationFactory):
    """
    Returns a PrescriberOrganization() object with a related PrescriberMembership() object.

    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    membership = factory.RelatedFactory(PrescriberMembershipFactory, "organization")


class PrescriberOrganizationWith2MembershipFactory(PrescriberOrganizationFactory):
    """
    Returns a PrescriberOrganization() object with 2 PrescriberMembership() objects.

    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    membership1 = factory.RelatedFactory(PrescriberMembershipFactory, "organization")
    membership2 = factory.RelatedFactory(PrescriberMembershipFactory, "organization", is_admin=False)


class AuthorizedPrescriberOrganizationWithMembershipFactory(PrescriberOrganizationWithMembershipFactory):
    """
    Returns a PrescriberOrganization() object with a related authorized PrescriberMembership() object.

    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    is_authorized = True
    authorization_status = models.PrescriberOrganization.AuthorizationStatus.VALIDATED


class PrescriberPoleEmploiFactory(PrescriberOrganizationFactory):
    code_safir_pole_emploi = factory.fuzzy.FuzzyText(length=5, chars=string.digits)
    is_authorized = True
    kind = models.PrescriberOrganization.Kind.PE
    authorization_status = models.PrescriberOrganization.AuthorizationStatus.VALIDATED
