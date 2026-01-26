import datetime
import uuid

import factory
import factory.fuzzy
from django.utils import timezone

from itou.nexus.enums import Auth, NexusStructureKind, NexusUserKind, Role, Service
from itou.nexus.models import NexusMembership, NexusRessourceSyncStatus, NexusStructure, NexusUser
from itou.nexus.utils import service_id


class NexusUserFactory(factory.django.DjangoModelFactory):
    id = factory.LazyAttribute(lambda o: service_id(o.source, o.source_id))
    source = factory.fuzzy.FuzzyChoice(Service)
    source_id = factory.LazyFunction(uuid.uuid4)
    kind = factory.fuzzy.FuzzyChoice(NexusUserKind)
    source_kind = factory.SelfAttribute("kind")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.Sequence("email{}@domain.com".format)
    phone = factory.Faker("phone_number", locale="fr_FR")
    last_login = factory.fuzzy.FuzzyDateTime(datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC), timezone.now())
    auth = factory.fuzzy.FuzzyChoice(Auth)

    class Meta:
        model = NexusUser
        skip_postgeneration_save = True

    class Params:
        with_membership = factory.Trait(
            membership=factory.RelatedFactory(
                "tests.nexus.factories.NexusMembershipFactory", "user", source=factory.SelfAttribute("..source")
            ),
        )


class NexusStructureFactory(factory.django.DjangoModelFactory):
    id = factory.LazyAttribute(lambda o: service_id(o.source, o.source_id))
    source = factory.fuzzy.FuzzyChoice(Service)
    source_id = factory.LazyFunction(uuid.uuid4)
    source_kind = factory.SelfAttribute("kind")

    kind = factory.fuzzy.FuzzyChoice(NexusStructureKind)
    name = factory.Faker("company", locale="fr_FR")
    email = factory.Sequence("email{}@domain.com".format)
    phone = factory.Faker("phone_number", locale="fr_FR")

    website = factory.Faker("url")
    accessibility = factory.LazyFunction(lambda: "https://acceslibre.beta.gouv.fr/" + str(uuid.uuid4()))
    description = factory.Faker("sentence", locale="fr_FR")
    source_link = factory.Faker("url")

    class Meta:
        model = NexusStructure


class NexusMembershipFactory(factory.django.DjangoModelFactory):
    id = factory.LazyAttribute(lambda o: service_id(o.source, o.source_id))
    source_id = factory.LazyFunction(uuid.uuid4)
    source = factory.fuzzy.FuzzyChoice(Service)
    user = factory.SubFactory(NexusUserFactory, source=factory.SelfAttribute("..source"))
    structure = factory.SubFactory(NexusStructureFactory, source=factory.SelfAttribute("..source"))
    role = factory.fuzzy.FuzzyChoice(Role)

    class Meta:
        model = NexusMembership


class NexusRessourceSyncStatusFactory(factory.django.DjangoModelFactory):
    service = factory.fuzzy.FuzzyChoice(Service)
    valid_since = factory.LazyFunction(timezone.now)

    class Meta:
        model = NexusRessourceSyncStatus
