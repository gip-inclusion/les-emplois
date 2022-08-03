import string

import factory
import factory.fuzzy

from itou.common_apps.address.departments import DEPARTMENTS
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.factories import PrescriberFactory


class PrescriberOrganizationFactory(factory.django.DjangoModelFactory):
    """Returns a PrescriberOrganization() object."""

    class Meta:
        model = PrescriberOrganization

    class Params:
        authorized = factory.Trait(
            is_authorized=True,
            authorization_status=PrescriberAuthorizationStatus.VALIDATED,
        )
        with_pending_authorization = factory.Trait(
            authorization_status=PrescriberAuthorizationStatus.NOT_SET,
        )

    name = factory.Faker("name", locale="fr_FR")
    # Don't start a SIRET with 0.
    siret = factory.fuzzy.FuzzyText(length=13, chars=string.digits, prefix="1")
    phone = factory.fuzzy.FuzzyText(length=10, chars=string.digits)
    email = factory.Faker("email", locale="fr_FR")
    kind = PrescriberOrganizationKind.PE
    department = factory.fuzzy.FuzzyChoice(DEPARTMENTS.keys())


class PrescriberMembershipFactory(factory.django.DjangoModelFactory):
    """
    Returns a PrescriberMembership() object with:
    - its related PrescriberOrganization()
    - its related User()

    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    class Meta:
        model = PrescriberMembership

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


class PrescriberPoleEmploiFactory(PrescriberOrganizationFactory):
    code_safir_pole_emploi = factory.fuzzy.FuzzyText(length=5, chars=string.digits)
    is_authorized = True
    kind = PrescriberOrganizationKind.PE
    authorization_status = PrescriberAuthorizationStatus.VALIDATED
