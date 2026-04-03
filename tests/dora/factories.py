import datetime

import factory

from itou.dora.models import ReferenceDatum, ReferenceDatumKind, Service, Structure


class ReferenceDatumFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ReferenceDatum
        django_get_or_create = ("kind", "value")

    kind = ReferenceDatumKind.SOURCE
    value = factory.Sequence(lambda n: f"source-{n}")
    label = factory.LazyAttribute(lambda o: o.value.title())


class StructureFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Structure

    uid = factory.Sequence(lambda n: f"structure-uid-{n}")
    source = factory.SubFactory(ReferenceDatumFactory, kind=ReferenceDatumKind.SOURCE)
    name = factory.Sequence(lambda n: f"Structure {n}")
    updated_on = datetime.date(2025, 1, 1)


class ServiceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Service
        skip_postgeneration_save = True

    uid = factory.Sequence(lambda n: f"service-uid-{n}")
    source = factory.SubFactory(ReferenceDatumFactory, kind=ReferenceDatumKind.SOURCE)
    structure = factory.SubFactory(StructureFactory)
    name = factory.Sequence(lambda n: f"Service {n}")
    description = "Description du service."
    updated_on = datetime.date(2025, 1, 1)
