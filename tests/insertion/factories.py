import datetime
import uuid

import factory
from django.utils import timezone

from itou.insertion.enums import MobilizationEventKind, OrientationRefusalReason, OrientationStatus
from itou.insertion.models import (
    GenericReferenceItem,
    GenericReferenceItemKind,
    GenericReferenceItemSource,
    MobilizationEvent,
    Orientation,
    OrientationProcessLink,
    Service,
    Structure,
)
from itou.job_applications.enums import SenderKind


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

    class Params:
        for_snapshot = factory.Trait(
            uid="structure-uid",
            name="Les joies de l’apprentissage",
            description="Une structure spécialisé dans les apprentissages.",
        )


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

    class Params:
        for_snapshot = factory.Trait(
            uid="service-uid",
            structure__for_snapshot=True,
            name="Aide aux devoirs",
            description="Un service d’aide aux devoirs pour tous les niveaux.",
            contact_email="service.contact@email.fake",
            address_line_1="13 rue de la porte",
            post_code="29200",
            city="Brest",
        )

    @factory.post_generation
    def receptions(self, create, extracted, **kwargs):
        if create:
            self.receptions.set(extracted if extracted is not None else [InPersonReceptionFactory()])

    @factory.post_generation
    def thematics(self, create, extracted, **kwargs):
        if create:
            self.thematics.set(extracted if extracted is not None else [DefaultThematicFactory()])


class MobilizationEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MobilizationEvent

    session_key = factory.LazyFunction(lambda: str(uuid.uuid4()).replace("-", ""))
    kind = MobilizationEventKind.STRUCTURE_CONTACT
    structure = factory.SubFactory(StructureFactory)


class OrientationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Orientation

    id = factory.LazyFunction(uuid.uuid4)  # Expected in Dora response
    beneficiary = factory.SubFactory("tests.users.factories.JobSeekerFactory")
    sender = factory.SubFactory("tests.users.factories.PrescriberFactory")
    sender_kind = SenderKind.PRESCRIBER
    sender_prescriber_organization = factory.SubFactory("tests.prescribers.factories.PrescriberOrganizationFactory")
    sender_company = None
    service = factory.SubFactory(ServiceFactory)
    referent_first_name = factory.Faker("first_name", locale="fr_FR")
    referent_last_name = factory.Faker("last_name", locale="fr_FR")
    referent_email = factory.Faker("email")
    referent_phone = "0142030405"
    data_protection_commitment = True
    refusal_reasons = factory.LazyAttribute(
        lambda obj: [OrientationRefusalReason.NOT_MOBILE] if obj.status == OrientationStatus.REFUSED else []
    )
    status = OrientationStatus.PENDING

    class Params:
        for_snapshot = factory.Trait(
            beneficiary__for_snapshot=True,
            sender__for_snapshot=True,
            sender_prescriber_organization__for_snapshot=True,
            service__for_snapshot=True,
            referent_first_name="Flora",
            referent_last_name="Tristan",
            referent_email="prescriptrice@inclusion.gouv.fr",
            referent_phone="0102030405",
        )


class OrientationProcessLinkFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrientationProcessLink

    orientation = factory.SubFactory(OrientationFactory)
