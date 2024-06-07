import string

import factory
import factory.fuzzy

from itou.common_apps.address.departments import department_from_postcode
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from tests.users.factories import PrescriberFactory
from tests.utils.test import create_fake_postcode


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
        for_snapshot = factory.Trait(
            name="Pres. Org.",
            address_line_1="39 rue d'Artois",
            post_code="75008",
            department="75",
            city="Paris",
            email="contact@Presorg.fr",
            phone="0612345678",
            siret="012345678910",
        )

    name = factory.Faker("name", locale="fr_FR")
    # Don't start a SIRET with 0.
    siret = factory.fuzzy.FuzzyText(length=13, chars=string.digits, prefix="1")
    phone = factory.fuzzy.FuzzyText(length=10, chars=string.digits)
    email = factory.Faker("email", locale="fr_FR")
    kind = PrescriberOrganizationKind.PE
    post_code = factory.LazyFunction(create_fake_postcode)
    department = factory.LazyAttribute(lambda o: department_from_postcode(o.post_code))


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

    class Meta:
        skip_postgeneration_save = True

    membership = factory.RelatedFactory(PrescriberMembershipFactory, "organization")


class PrescriberOrganizationWith2MembershipFactory(PrescriberOrganizationFactory):
    """
    Returns a PrescriberOrganization() object with 2 PrescriberMembership() objects.

    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    class Meta:
        skip_postgeneration_save = True

    membership1 = factory.RelatedFactory(PrescriberMembershipFactory, "organization")
    membership2 = factory.RelatedFactory(PrescriberMembershipFactory, "organization", is_admin=False)


class PrescriberPoleEmploiFactory(PrescriberOrganizationFactory):
    code_safir_pole_emploi = factory.fuzzy.FuzzyText(length=5, chars=string.digits)
    is_authorized = True
    kind = PrescriberOrganizationKind.PE
    authorization_status = PrescriberAuthorizationStatus.VALIDATED


class PrescriberPoleEmploiWithMembershipFactory(PrescriberPoleEmploiFactory):
    class Meta:
        skip_postgeneration_save = True

    membership = factory.RelatedFactory(PrescriberMembershipFactory, "organization")
