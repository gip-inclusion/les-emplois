import factory
from django.utils import timezone

from itou.insertion.models import GenericReferenceItem, GenericReferenceItemKind, GenericReferenceItemSource, Structure


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
