import logging

from data_inclusion.schema import v1 as data_inclusion_v1
from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import BooleanField, Exists, OuterRef, Q, Value
from django.utils import timezone

from itou.companies.models import Company
from itou.insertion.enums import (
    BeneficiaryContactPreference,
    GenericReferenceItemKind,
    GenericReferenceItemSource,
    MobilizationEventKind,
    OrientationStatus,
)
from itou.job_applications.enums import SenderKind
from itou.prescribers.models import PrescriberOrganization
from itou.users.models import User
from itou.utils.storage.s3 import generate_dora_storage_url
from itou.utils.validators import validate_post_code


logger = logging.getLogger(__name__)


SOURCE_DORA_VALUE = "dora"

SERVICE_SEARCH_RADIUS_KM = 50


class GeolocatedAddressMixin(models.Model):
    """Address fields for objects imported from data·inclusion and DORA.

    Deliberately kept separate from `common_apps.address.AddressMixin`: imported objects
    are already geocoded upstream and never go through our BAN geocoding pipeline.
    Reusing `AddressMixin` would pull in unused fields and behaviour (geocoding score,
    department validation, QPV/ZRR lookups…) and couple this import to unrelated business
    logic. A dedicated mixin keeps the `insertion` app independent and free of side
    effects.
    """

    address_line_1 = models.CharField(verbose_name="adresse", blank=True)
    address_line_2 = models.CharField(
        verbose_name="complément d'adresse",
        blank=True,
        help_text="Appartement, suite, bloc, bâtiment, boite postale, etc.",
    )
    post_code = models.CharField(
        verbose_name="code postal",
        validators=[validate_post_code],
        max_length=5,
        blank=True,
    )
    city = models.CharField(verbose_name="ville", blank=True)
    insee_city = models.ForeignKey("cities.City", on_delete=models.SET_NULL, null=True, related_name="+")

    coordinates = gis_models.PointField(geography=True, null=True, blank=True)

    @property
    def address_on_one_line(self):
        if not all([self.address_line_1, self.post_code, self.city]):
            return None
        fields = [
            self.address_line_1,
            self.address_line_2,
            f"{self.post_code} {self.city}",
        ]
        return ", ".join(field for field in fields if field)

    class Meta:
        abstract = True


class GenericReferenceItem(models.Model):
    source = models.CharField(choices=GenericReferenceItemSource.choices)
    kind = models.CharField(verbose_name="type", choices=GenericReferenceItemKind.choices)
    value = models.CharField(verbose_name="valeur")
    label = models.CharField(verbose_name="libellé")
    description = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    class Meta:
        verbose_name = "référentiel data·inclusion & DORA"
        verbose_name_plural = "référentiels data·inclusion & DORA"
        constraints = [
            models.UniqueConstraint(fields=["source", "kind", "value"], name="unique_value_for_kind_and_source"),
        ]

    def __str__(self):
        return self.label

    @classmethod
    def in_person_reception_ids(cls):
        return list(
            cls.objects.filter(value=data_inclusion_v1.ModeAccueil.EN_PRESENTIEL.value).values_list("id", flat=True)
        )

    @classmethod
    def remote_reception_ids(cls):
        return list(
            cls.objects.filter(value=data_inclusion_v1.ModeAccueil.A_DISTANCE.value).values_list("id", flat=True)
        )


class Structure(GeolocatedAddressMixin, models.Model):
    uid = models.CharField(unique=True)

    source = models.ForeignKey(
        to=GenericReferenceItem,
        on_delete=models.RESTRICT,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.SOURCE,
        },
        related_name="+",
    )
    source_link = models.URLField(verbose_name="lien de la source", blank=True, max_length=512)

    siret = models.CharField(blank=True)

    name = models.CharField(verbose_name="nom")
    description = models.TextField(blank=True)
    website = models.URLField(verbose_name="site web", max_length=2000, blank=True)

    email = models.EmailField(verbose_name="e-mail", blank=True)
    phone = models.CharField(verbose_name="téléphone", max_length=20, blank=True)

    opening_hours = models.CharField(verbose_name="horaires d'accueil", blank=True)

    reseaux_porteurs = models.ManyToManyField(
        verbose_name="réseaux porteurs",
        to=GenericReferenceItem,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.NETWORK,
        },
        related_name="+",
        blank=True,
    )

    updated_on = models.DateField(verbose_name="date de modification data·inclusion")

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    class Meta:
        verbose_name = "structure d'insertion"
        verbose_name_plural = "structures d'insertion"

    def __str__(self):
        return self.uid


class ServiceQuerySet(models.QuerySet):
    def search(self, *, city, thematics, reception, service_types):
        # NOTE(vperron): always search with ids directly instead of letting Django create JOINs with .through
        # as it might become horrribly slow on those tables
        thematic_ids = list(GenericReferenceItem.objects.filter(value__in=thematics).values_list("id", flat=True))
        eligibility_codes = [code for code in [city.code_insee, city.department, city.siren_epci, "france"] if code]
        # An empty eligibility zone means national availability (aligned on data·inclusion).
        eligibility_filter = Q(eligibility_zones__overlap=eligibility_codes) | Q(eligibility_zones=[])
        queryset = (
            self.annotate(
                distance=Distance("coordinates", city.coords) / 1000,
                has_thematic=Exists(
                    self.model.thematics.through.objects.filter(
                        service=OuterRef("pk"),
                        genericreferenceitem_id__in=thematic_ids,
                    )
                ),
            )
            .filter(
                has_thematic=True,
                coordinates__isnull=False,
                **({"kind__value__in": service_types} if service_types else {}),
            )
            .exclude(city="")
        )

        if reception == data_inclusion_v1.ModeAccueil.EN_PRESENTIEL.value:
            return (
                queryset.filter(
                    receptions__id__in=GenericReferenceItem.in_person_reception_ids(),
                    coordinates__dwithin=(city.coords, D(km=SERVICE_SEARCH_RADIUS_KM)),
                )
                .filter(eligibility_filter)
                .annotate(
                    is_in_person=Value(True, output_field=BooleanField()),
                    is_remote=Value(False, output_field=BooleanField()),
                )
                .order_by("distance", "pk")
            )

        if reception == data_inclusion_v1.ModeAccueil.A_DISTANCE.value:
            return (
                queryset.filter(receptions__id__in=GenericReferenceItem.remote_reception_ids())
                .filter(eligibility_filter)
                .annotate(
                    is_in_person=Value(False, output_field=BooleanField()),
                    is_remote=Value(True, output_field=BooleanField()),
                )
                .order_by("distance", "pk")
            )

        return (
            queryset.annotate(
                is_in_person=Exists(
                    self.model.receptions.through.objects.filter(
                        service=OuterRef("pk"),
                        genericreferenceitem_id__in=GenericReferenceItem.in_person_reception_ids(),
                    )
                ),
                is_remote=Exists(
                    self.model.receptions.through.objects.filter(
                        service=OuterRef("pk"),
                        genericreferenceitem_id__in=GenericReferenceItem.remote_reception_ids(),
                    )
                ),
            )
            .filter(
                Q(is_in_person=True) & Q(coordinates__dwithin=(city.coords, D(km=SERVICE_SEARCH_RADIUS_KM)))
                | Q(is_remote=True)
            )
            .filter(eligibility_filter)
            .order_by("-is_in_person", "distance", "pk")
        )


class Service(GeolocatedAddressMixin, models.Model):
    uid = models.CharField(unique=True)

    source = models.ForeignKey(
        to=GenericReferenceItem,
        on_delete=models.RESTRICT,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.SOURCE,
        },
        related_name="+",
    )
    source_link = models.URLField(verbose_name="lien vers la source", blank=True, max_length=512)

    structure = models.ForeignKey(Structure, on_delete=models.CASCADE, related_name="services")

    name = models.CharField(verbose_name="nom")
    description = models.TextField(verbose_name="description complète")
    description_short = models.TextField(verbose_name="description courte", blank=True)

    kind = models.ForeignKey(
        verbose_name="type de service",
        to=GenericReferenceItem,
        on_delete=models.RESTRICT,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.SERVICE_KIND,
        },
        null=True,
        related_name="+",
    )

    thematics = models.ManyToManyField(
        verbose_name="thématiques",
        to=GenericReferenceItem,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.THEMATIC,
        },
        related_name="+",
    )

    fee = models.ForeignKey(
        verbose_name="frais",
        to=GenericReferenceItem,
        on_delete=models.RESTRICT,
        limit_choices_to={"source": GenericReferenceItemSource.DATA_INCLUSION, "kind": GenericReferenceItemKind.FEE},
        null=True,
        related_name="+",
    )
    fee_details = models.TextField(verbose_name="frais - précisions", blank=True)

    publics = models.ManyToManyField(
        verbose_name="publics visés",
        to=GenericReferenceItem,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.PUBLIC,
        },
        related_name="+",
    )
    publics_details = models.TextField(verbose_name="publics visés - précisions", blank=True)

    access_conditions_di = models.TextField(verbose_name="critères d’admission (data·inclusion)", blank=True)
    access_conditions_dora = ArrayField(
        verbose_name="critères d’admission (DORA)",
        base_field=models.CharField(),
        default=list,
        blank=True,
    )

    eligibility_zones = ArrayField(
        verbose_name="zones d’éligibilité",
        base_field=models.CharField(),
        default=list,
        blank=True,
    )

    receptions = models.ManyToManyField(
        verbose_name="modes d'accueil",
        to=GenericReferenceItem,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.RECEPTION,
        },
        related_name="+",
    )

    # data·inclusion's mobilization fields
    mobilizations = models.ManyToManyField(
        verbose_name="modes de mobilisation",
        to=GenericReferenceItem,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.MOBILIZATION,
        },
        related_name="+",
    )
    mobilizations_details = models.TextField(verbose_name="modes de mobilisation - précisions", blank=True)
    mobilization_publics = models.ManyToManyField(
        verbose_name="personne mobilisatrices",
        to=GenericReferenceItem,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.MOBILIZATION_PUBLIC,
        },
        related_name="+",
    )

    # DORA's mobilization fields
    mobilization_modes_beneficiaries = models.ManyToManyField(
        verbose_name="comment mobiliser la solution en tant que bénéficiaire",
        to=GenericReferenceItem,
        limit_choices_to={
            "source": GenericReferenceItemSource.DORA,
            "kind": GenericReferenceItemKind.MOBILIZATION_BENEFICIARY,
        },
        related_name="+",
    )
    mobilization_modes_beneficiaries_external_form_link = models.URLField(
        verbose_name="lien vers le formulaire externe", blank=True, max_length=2000
    )
    mobilization_modes_beneficiaries_external_form_link_text = models.CharField(
        verbose_name="l’intitulé du lien vers le formulaire externe",
        blank=True,
    )
    mobilization_modes_beneficiaries_other = models.CharField(verbose_name="autre", blank=True)
    mobilization_modes_professionals = models.ManyToManyField(
        verbose_name="comment orienter un bénéficiaire en tant qu’accompagnateur",
        to=GenericReferenceItem,
        limit_choices_to={
            "source": GenericReferenceItemSource.DORA,
            "kind": GenericReferenceItemKind.MOBILIZATION_PROFESSIONAL,
        },
        related_name="+",
    )
    mobilization_modes_professionals_external_form_link = models.URLField(
        verbose_name="lien vers le formulaire externe", blank=True, max_length=2000
    )
    mobilization_modes_professionals_external_form_link_text = models.CharField(
        verbose_name="l’intitulé du lien vers le formulaire externe",
        blank=True,
    )
    mobilization_modes_professionals_other = models.CharField(verbose_name="autre", blank=True)

    credentials = ArrayField(
        verbose_name="justificatifs à fournir",
        base_field=models.CharField(),
        default=list,
        blank=True,
    )
    credentials_documents = ArrayField(
        verbose_name="documents justificatifs à compléter",
        base_field=models.CharField(max_length=1024),  # See File().key for `max_length` rational
        default=list,
        blank=True,
    )
    credentials_online_form = models.URLField(
        verbose_name="formulaire en ligne à compléter",
        blank=True,
        # No `max_length` to use Django's default just like DORA
    )

    funding_labels = models.ManyToManyField(
        verbose_name="labels de financement",
        to=GenericReferenceItem,
        limit_choices_to={"source": GenericReferenceItemSource.DORA, "kind": GenericReferenceItemKind.FUNDING_LABEL},
        related_name="+",
    )

    opening_hours = models.CharField(verbose_name="horaires d'accueil", blank=True)
    opening_hours_text = models.CharField(verbose_name="horaires d'accueil (texte libre)", blank=True)

    contact_full_name = models.CharField(verbose_name="contact", blank=True)
    contact_email = models.EmailField(verbose_name="e-mail du contact", blank=True)
    contact_phone = models.CharField(verbose_name="téléphone du contact", max_length=20, blank=True)
    contact_is_public = models.BooleanField(verbose_name="informations du contact publiques", default=True)

    is_orientable_with_form = models.BooleanField(verbose_name="formulaire d'orientation actif", default=True)
    average_orientation_response_delay_days = models.PositiveIntegerField(
        verbose_name="temps moyen de réponse aux orientations (jour)", null=True
    )

    dora_synced_at = models.DateTimeField(verbose_name="date de synchronisation DORA", null=True, blank=True)

    updated_on = models.DateField(verbose_name="date de modification data·inclusion")

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    @property
    def is_dora(self):
        return self.source.value == "dora"

    @property
    def prerequisites(self) -> list[str]:
        if self.is_dora:
            return [*self.access_conditions_dora, *self.credentials]
        return [line for line in self.access_conditions_di.split("\\n") if line]

    @property
    def has_prerequisites(self) -> bool:
        return bool(self.prerequisites)

    @property
    def has_orientation_action(self):
        return self.is_orientable_with_form or bool(self.mobilization_modes_professionals_external_form_link)

    def has_mobilization_modes(self):
        return (not self.is_dora and bool(self.mobilizations.all())) or (
            self.is_dora
            and (
                bool(self.mobilization_modes_professionals.all())
                or self.mobilization_modes_professionals_external_form_link
                or self.mobilization_modes_professionals_other
                or bool(self.mobilization_modes_beneficiaries.all())
                or self.mobilization_modes_beneficiaries_external_form_link
                or self.mobilization_modes_beneficiaries_other
            )
        )

    def generate_credential_documents_info(self) -> list[tuple[str, str]]:
        return [
            (form_key.split("/")[-1], generate_dora_storage_url(form_key)) for form_key in self.credentials_documents
        ]

    objects = ServiceQuerySet.as_manager()

    class Meta:
        verbose_name = "service d'insertion"
        verbose_name_plural = "services d'insertion"

    def __str__(self):
        return self.uid

    @property
    def reception_location_label(self):
        reception_values = {reception.value for reception in self.receptions.all()}
        if (
            data_inclusion_v1.ModeAccueil.A_DISTANCE.value in reception_values
            and data_inclusion_v1.ModeAccueil.EN_PRESENTIEL.value not in reception_values
        ):
            return "à distance"
        if self.city:
            return self.city
        return None

    @property
    def is_local(self):
        return self.is_in_person and self.distance is not None and self.distance <= SERVICE_SEARCH_RADIUS_KM


class MobilizationEventManager(models.Manager):
    def create_mobilization_event(
        self, *, session_key, kind, user, organization, structure, service=None, service_external_link=""
    ):
        # The provided organization can be a prescriber organization, a company,
        # or None if the user is not authenticated
        prescriber_organization = organization if isinstance(organization, PrescriberOrganization) else None
        company = organization if isinstance(organization, Company) else None

        if user.is_authenticated and not prescriber_organization and not company:
            # Ignore job seekers, labor inspectors and itou_staff
            return

        MobilizationEvent(
            session_key=session_key,
            kind=kind,
            user=user if user.is_authenticated else None,
            prescriber_organization=prescriber_organization,
            company=company,
            structure=structure,
            service=service,
            service_external_link=service_external_link,
        ).save()


class MobilizationEvent(models.Model):
    session_key = models.CharField(verbose_name="clé de session", max_length=40)
    kind = models.CharField(verbose_name="type", choices=MobilizationEventKind)
    user = models.ForeignKey(
        User, verbose_name="prescripteur ou employeur", on_delete=models.CASCADE, null=True, related_name="+"
    )
    prescriber_organization = models.ForeignKey(
        PrescriberOrganization,
        verbose_name="organisation prescriptrice",
        on_delete=models.CASCADE,
        null=True,
        related_name="+",
    )
    company = models.ForeignKey(
        Company,
        verbose_name="entreprise",
        on_delete=models.CASCADE,
        null=True,
        related_name="+",
    )
    service = models.ForeignKey(Service, on_delete=models.CASCADE, null=True, related_name="+")
    structure = models.ForeignKey(Structure, on_delete=models.CASCADE, related_name="+")
    service_external_link = models.CharField(verbose_name="lien externe", blank=True)
    created_at = models.DateTimeField(verbose_name="date de création", auto_now=True)

    objects = MobilizationEventManager()

    class Meta:
        verbose_name = "intention de mise en relation (iMER)"
        verbose_name_plural = "intentions de mise en relation (iMER)"

        constraints = [
            models.CheckConstraint(
                name="service_and_structure_kind_coherence",
                condition=models.Q(
                    kind__in=[
                        MobilizationEventKind.SERVICE_ORIENTATION,
                        MobilizationEventKind.SERVICE_CONTACT,
                        MobilizationEventKind.SERVICE_EXT_LINK,
                    ],
                    service__isnull=False,
                )
                | models.Q(kind=MobilizationEventKind.STRUCTURE_CONTACT, service__isnull=True),
            ),
            models.CheckConstraint(
                name="authenticated_user_has_organization",
                condition=models.Q(user=None, prescriber_organization=None, company=None)
                | (
                    models.Q(user__isnull=False)
                    & (models.Q(prescriber_organization__isnull=False) | models.Q(company__isnull=False))
                ),
            ),
            models.CheckConstraint(
                name="service_external_link_coherence",
                condition=models.Q(kind=MobilizationEventKind.SERVICE_EXT_LINK) & ~models.Q(service_external_link="")
                | (~models.Q(kind=MobilizationEventKind.SERVICE_EXT_LINK) & models.Q(service_external_link="")),
            ),
        ]


class Orientation(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)

    beneficiary = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="bénéficiaire",
        on_delete=models.RESTRICT,
        related_name="orientations",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="émetteur",
        on_delete=models.RESTRICT,
        related_name="orientations_sent",
    )
    sender_kind = models.CharField(
        verbose_name="type de l'émetteur",
        choices=SenderKind.choices,
    )
    sender_prescriber_organization = models.ForeignKey(
        "prescribers.PrescriberOrganization",
        verbose_name="organisation prescriptrice émettrice",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
        related_name="orientations_sent",
    )
    sender_company = models.ForeignKey(
        "companies.Company",
        verbose_name="entreprise émettrice",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
        related_name="orientations_sent",
    )
    service = models.ForeignKey(
        Service,
        verbose_name="service d'insertion",
        # FIXME: import_structures_and_services may delete services and would fail.
        # Define what we want to do (archive? drop orientations?) and update the script if necessary.
        on_delete=models.RESTRICT,
        related_name="orientations",
    )

    # Not collected by the current orientation wizard; required for the detail page.
    # Populated later via wizard extensions.
    beneficiary_contact_preferences = ArrayField(
        models.CharField(max_length=10, choices=BeneficiaryContactPreference.choices),
        verbose_name="préférences de contact du bénéficiaire",
        default=list,
        blank=True,
    )
    beneficiary_other_contact_method = models.CharField(
        verbose_name="autre méthode de contact du bénéficiaire",
        max_length=280,
        blank=True,
    )
    beneficiary_availability = models.DateField(
        verbose_name="disponibilité du bénéficiaire",
        null=True,
        blank=True,
    )
    requirements = ArrayField(
        models.CharField(max_length=480),
        verbose_name="critères",
        default=list,
        blank=True,
    )
    situation = ArrayField(
        models.CharField(max_length=480),
        verbose_name="situation",
        default=list,
        blank=True,
    )
    situation_other = models.CharField(
        verbose_name="situation - autre",
        max_length=480,
        blank=True,
    )

    referent_last_name = models.CharField(verbose_name="nom du référent", max_length=140)
    referent_first_name = models.CharField(verbose_name="prénom du référent", max_length=140)
    referent_phone = models.CharField(verbose_name="téléphone du référent", max_length=10, blank=True)
    referent_email = models.EmailField(verbose_name="e-mail du référent")
    orientation_reasons = models.TextField(verbose_name="motif de l'orientation", blank=True)

    status = models.CharField(
        verbose_name="statut",
        max_length=20,
        choices=OrientationStatus.choices,
        default=OrientationStatus.PENDING,
    )
    processing_date = models.DateTimeField(verbose_name="date de traitement", null=True, blank=True)
    duration_weekly_hours = models.PositiveIntegerField(
        verbose_name="nombre d'heures par semaine",
        null=True,
        blank=True,
    )
    duration_weeks = models.PositiveIntegerField(
        verbose_name="nombre de semaines",
        null=True,
        blank=True,
    )

    data_protection_commitment = models.BooleanField(
        verbose_name="engagement RGPD accompagnateur",
        default=False,
    )

    attachments = ArrayField(
        models.CharField(max_length=1024),
        verbose_name="documents joints",
        blank=True,
        default=list,
    )

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    class Meta:
        verbose_name = "orientation"
        verbose_name_plural = "orientations"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        sender_kind=SenderKind.PRESCRIBER,
                        sender_prescriber_organization__isnull=False,
                        sender_company__isnull=True,
                    )
                    | Q(
                        sender_kind=SenderKind.EMPLOYER,
                        sender_company__isnull=False,
                        sender_prescriber_organization__isnull=True,
                    )
                ),
                name="orientation_sender_organization_consistent",
            ),
        ]

    def __str__(self):
        return str(self.id)

    @property
    def sender_organization(self):
        return self.sender_prescriber_organization or self.sender_company

    @property
    def attachments_details(self):
        return [(form_key.split("/")[-1], generate_dora_storage_url(form_key)) for form_key in self.attachments]

    @property
    def beneficiary_contact_preferences_display(self):
        choices = [
            BeneficiaryContactPreference(preference).label
            for preference in self.beneficiary_contact_preferences
            if preference != BeneficiaryContactPreference.OTHER.value
        ]
        if (
            BeneficiaryContactPreference.OTHER.value in self.beneficiary_contact_preferences
            and self.beneficiary_other_contact_method
        ):
            choices.append(f"{BeneficiaryContactPreference.OTHER.label} ({self.beneficiary_other_contact_method})")
        return ", ".join(choices)
