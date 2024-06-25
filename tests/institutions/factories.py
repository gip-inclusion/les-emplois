import factory

from itou.common_apps.address.departments import DEPARTMENTS
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution, InstitutionMembership
from tests.users.factories import LaborInspectorFactory


class InstitutionFactory(factory.django.DjangoModelFactory):
    """Returns an Institution() object."""

    class Meta:
        model = Institution

    name = factory.Faker("name", locale="fr_FR")
    kind = InstitutionKind.DDETS_IAE
    department = factory.Iterator(DEPARTMENTS.keys())


class InstitutionMembershipFactory(factory.django.DjangoModelFactory):
    """
    Returns a InstitutionMembership() object with:
    - its related Institution()
    - its related User()

    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    class Meta:
        model = InstitutionMembership

    user = factory.SubFactory(LaborInspectorFactory)
    institution = factory.SubFactory(InstitutionFactory)
    is_admin = True
    is_active = True


class InstitutionWithMembershipFactory(InstitutionFactory):
    """
    Returns a Institution() object with a related InstitutionMembership() object.

    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    class Meta:
        skip_postgeneration_save = True

    membership = factory.RelatedFactory(InstitutionMembershipFactory, "institution")


class InstitutionWith2MembershipFactory(InstitutionFactory):
    """
    Returns a Institution() object with 2 InstitutionMembership() objects.

    https://factoryboy.readthedocs.io/en/latest/recipes.html#many-to-many-relation-with-a-through
    """

    class Meta:
        skip_postgeneration_save = True

    membership1 = factory.RelatedFactory(InstitutionMembershipFactory, "institution")
    membership2 = factory.RelatedFactory(InstitutionMembershipFactory, "institution", is_admin=False)
