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


IN_PERSON_RECEPTION_VALUE = "en-presentiel"
REMOTE_RECEPTION_VALUE = "a-distance"
THEMATIC_VALUE = "mobilite--acceder-a-un-vehicule"
OTHER_THEMATIC_VALUE = "sante--acces-aux-soins"


class GenericReferenceItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = GenericReferenceItem

    source = GenericReferenceItemSource.DATA_INCLUSION
    kind = GenericReferenceItemKind.SOURCE
    value = factory.Sequence(lambda n: f"source-{n}")
    label = factory.Faker("word", locale="fr_FR")


class InPersonReceptionFactory(GenericReferenceItemFactory):
    class Meta:
        django_get_or_create = ("source", "kind", "value")

    kind = GenericReferenceItemKind.RECEPTION
    value = IN_PERSON_RECEPTION_VALUE
    label = IN_PERSON_RECEPTION_VALUE


class RemoteReceptionFactory(GenericReferenceItemFactory):
    class Meta:
        django_get_or_create = ("source", "kind", "value")

    kind = GenericReferenceItemKind.RECEPTION
    value = REMOTE_RECEPTION_VALUE
    label = REMOTE_RECEPTION_VALUE


class DefaultThematicFactory(GenericReferenceItemFactory):
    class Meta:
        django_get_or_create = ("source", "kind", "value")

    kind = GenericReferenceItemKind.THEMATIC
    value = THEMATIC_VALUE
    label = THEMATIC_VALUE


class OtherThematicFactory(GenericReferenceItemFactory):
    class Meta:
        django_get_or_create = ("source", "kind", "value")

    kind = GenericReferenceItemKind.THEMATIC
    value = OTHER_THEMATIC_VALUE
    label = OTHER_THEMATIC_VALUE


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

    @factory.post_generation
    def receptions(self, create, extracted, **kwargs):
        if create:
            self.receptions.set(extracted if extracted is not None else [InPersonReceptionFactory()])

    @factory.post_generation
    def thematics(self, create, extracted, **kwargs):
        if create:
            self.thematics.set(extracted if extracted is not None else [DefaultThematicFactory()])
