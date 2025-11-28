import datetime
import uuid

import factory
import factory.fuzzy
from django.utils import timezone

from itou.nexus.enums import Auth, Role, Service, StructureKind, UserKind
from itou.nexus.models import Membership, Structure, User
from itou.nexus.utils import unique_id


class NexusUserFactory(factory.django.DjangoModelFactory):
    id = factory.LazyAttribute(lambda o: unique_id(o.source_id, o.source))
    source = factory.fuzzy.FuzzyChoice(Service)
    source_id = factory.LazyFunction(uuid.uuid4)
    kind = factory.fuzzy.FuzzyChoice(UserKind)
    source_kind = factory.SelfAttribute("kind")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.Sequence("email{}@domain.com".format)
    phone = factory.Faker("phone_number", locale="fr_FR")
    last_login = factory.fuzzy.FuzzyDateTime(datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC), timezone.now())
    auth = factory.fuzzy.FuzzyChoice(Auth)

    class Meta:
        model = User
        skip_postgeneration_save = True

    class Params:
        with_membership = factory.Trait(
            membership=factory.RelatedFactory(
                "tests.nexus.factories.NexusMembershipFactory", "user", source=factory.SelfAttribute("..source")
            ),
        )


class NexusStructureFactory(factory.django.DjangoModelFactory):
    id = factory.LazyAttribute(lambda o: unique_id(o.source_id, o.source))
    source = factory.fuzzy.FuzzyChoice(Service)
    source_id = factory.LazyFunction(uuid.uuid4)
    source_kind = factory.SelfAttribute("kind")

    kind = factory.fuzzy.FuzzyChoice(StructureKind)
    name = factory.Faker("company", locale="fr_FR")
    email = factory.Sequence("email{}@domain.com".format)
    phone = factory.Faker("phone_number", locale="fr_FR")

    class Meta:
        model = Structure


class NexusMembershipFactory(factory.django.DjangoModelFactory):
    source = factory.fuzzy.FuzzyChoice(Service)
    user = factory.SubFactory(NexusUserFactory, source=factory.SelfAttribute("..source"))
    structure = factory.SubFactory(NexusStructureFactory, source=factory.SelfAttribute("..source"))
    role = factory.fuzzy.FuzzyChoice(Role)

    class Meta:
        model = Membership
