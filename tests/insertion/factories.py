import datetime

import factory
from django.utils import timezone

from itou.insertion.models import (
    GenericReferenceItem,
    GenericReferenceItemKind,
    GenericReferenceItemSource,
    Service,
    Structure,
)


class GenericReferenceItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = GenericReferenceItem

    source = GenericReferenceItemSource.DATA_INCLUSION
    kind = GenericReferenceItemKind.SOURCE
    value = factory.Sequence(lambda n: f"source-{n}")
    label = factory.Faker("word", locale="fr_FR")


class StructureFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Structure

    uid = factory.Sequence(lambda n: f"structure-uid-{n}")
    source = factory.SubFactory(GenericReferenceItemFactory)
    name = factory.Faker("company", locale="fr_FR")
    description = factory.Faker("paragraph", locale="fr_FR")
    updated_on = factory.LazyFunction(timezone.localdate)


class ServiceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Service
        skip_postgeneration_save = True

    uid = factory.Sequence(lambda n: f"service-uid-{n}")
    source = factory.SubFactory(GenericReferenceItemFactory, kind=GenericReferenceItemKind.SOURCE)
    structure = factory.SubFactory(StructureFactory)
    name = factory.Sequence(lambda n: f"Service {n}")
    description = "Description du service."
    updated_on = datetime.date(2025, 1, 1)
